"""
Extraction pipeline — OWNER: Kelvin

Turns a payslip PDF into a PayslipExtract (slyp/contract.py). This is the
only place in the codebase that talks to an LLM, and the only place real
PII is anywhere near a network call, so the pipeline order below is not
negotiable:

    extract_text            pdfplumber, in memory, no OCR, no tables
    redact                  replace PII with tokens - FIRST
    financial_lines_only    allowlist filter - SECOND, after redaction
    assert_safe_to_send     final re-scan - THIRD, right before the call
    extract_payslip         orchestrates all of the above + the model call

Why that order, concretely: on a real payslip, "NI Number AB 12 34 56 C
National Insurance 0.00" is one line. The allowlist would keep that line
outright because it contains a currency amount - so if filtering ran
before redaction, the NI number would ride along with it. Redacting first
means the token, not the number, is what the allowlist sees.

Architecture rule: the model reads, the code calculates. The model never
computes reconciles, tax_year, or does arithmetic of any kind - it only
reports what's printed on the document, with a confidence per field.

Built against five real payslips (see tools/inspect_payslip.py output,
2026-08-14): text layers exist on all of them (no OCR needed for MVP),
extract_tables() returns rows of empty strings on all of them (ruled
lines, not tagged tables - hence extract_tables() is never called here),
and columns visually laid out side by side collapse into a single line of
extracted text, e.g.:

    Tax Code 1257L Income Tax 0.00
    NI Number AB 12 34 56 C National Insurance 0.00

No regex reliably recovers which label a mid-line value belongs to once
columns have collapsed like that - that ambiguity is exactly why this
step is an LLM call and not a parser.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import anthropic
import openai
import pdfplumber
from pydantic import BaseModel, Field, ValidationError

from .contract import Deductions, Frequency, Pay, PayslipExtract, Source, TaxCodeRead


# ==========================================================================
# Exceptions
# ==========================================================================
#
# All three follow slyp.types.UnsupportedPayslip's shape (a `reason`
# attribute plus a message) so callers can handle "we refused to guess"
# consistently wherever it happens in the pipeline.


class UnreadableDocument(Exception):
    """The PDF has no usable text layer, or pdfplumber could not open it."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class NotAPayslip(Exception):
    """The model reports this isn't a payslip, or its output doesn't fit
    the schema closely enough to trust."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RedactionFailure(Exception):
    """assert_safe_to_send found PII in a payload about to be sent. Fails
    closed: raising here must always mean the API call does not happen."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ==========================================================================
# Redaction
# ==========================================================================


@dataclass
class RedactionMap:
    """
    What redact() replaced, keyed by the token it used. Lets the UI show
    the user their own name/details back locally. This object is built
    from the same PII it describes, so it must never leave the server -
    nothing in this pipeline sends it anywhere, and it isn't part of
    PayslipExtract.
    """

    replacements: dict[str, list[str]] = field(default_factory=dict)
    employer_name: Optional[str] = None

    def record(self, token: str, original: str) -> None:
        self.replacements.setdefault(token, []).append(original)


# Separator class shared by every structured-number pattern below: space,
# period, hyphen or slash, any number of them, including a line break
# (\s matches \n). A real payslip prints these numbers with arbitrary
# internal punctuation ("AB 12 34 56 C", "AB.12.34.56.C", a value split
# across a wrapped line) - every character boundary tolerates this rather
# than assuming one canonical separator.
_SEP = r"[\s./-]*"

# NI number: two letters (excluding D,F,I,Q,U,V - not valid prefix
# letters), six digits, one suffix letter A-D.
_NI_NUMBER_RE = re.compile(
    rf"\b[A-CEGHJ-PR-TW-Z]{_SEP}[A-CEGHJ-PR-TW-Z]{_SEP}(?:\d{_SEP}){{6}}[A-D]\b",
    re.IGNORECASE,
)

# UK postcode, e.g. "SW1A 1AA", "ZZ99 9ZZ". Also doubles as the address
# catch: a postcode is usually the only reliably-shaped part of an
# address, so it gets its own token rather than trying to bound a whole
# address block with a regex.
_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)

# Sort code: three pairs of digits, each pair separated by one of
# space/hyphen/slash - "12-34-56", "12 34 56", "12/34/56", or mixed
# ("12-34/56"). Deliberately NOT "." here (unlike the other patterns in
# this section): two adjacent currency amounts like "37.60 13.85" would
# otherwise match as a fake sort code ("60 13.85") purely because a
# decimal point is a valid separator character - a collision that can't
# happen for NI numbers (which require letters at fixed positions no
# money figure has). Sort codes aren't printed with periods on a real
# payslip anyway; the reported gap (F6) was slashes, not periods.
# Separator is a literal space, hyphen or slash - NOT \s, which matches a
# newline.
#
# A sort code never spans a line break, but \s let this pattern match the
# tail of one line and the head of the next. On a work-record table with
# date-first rows it matched '46\n20/07' - the pence of one row's total, the
# line break, and the next row's DD/MM - and because redact() SUBSTITUTES
# over the match, the newline was consumed along with it. Three rows became
# one line reading "38.[BANK]/2026  ES602 Repair...", destroying both the
# total and the date and welding unrelated columns together. The merge was
# ours, not pdfplumber's: the extracted text still had the line breaks.
_SORT_CODE_RE = re.compile(r"\b\d{2}[- /]\d{2}[- /]\d{2}\b")

# Account number: 8 digits, each optionally separated from the next by
# one of the same characters (excluding "." for the same reason as sort
# code, above). Deliberately not label-anchored - real payslips don't
# always print an "Account Number:" label next to it. That also makes it
# the noisiest pattern here (an 8-digit reference number would also
# match); assert_safe_to_send and the allowlist are the backstops for
# what this over-redacts or misses, not this regex alone.
#
# Genuine collision, found live: a UK date in DD/MM/YYYY or DD-MM-YYYY
# format ("15/12/2025") is exactly 8 digits with the same separator
# tolerance, so it matches this pattern too - and since redact() runs
# before financial_lines_only(), the date was gone (replaced with
# "[BANK]") before the model ever saw it, silently breaking
# period.pay_date and everything derived from it for the single most
# common real-world date format. _looks_like_an_unambiguous_date() below
# exempts a match from account-number redaction only when it's shaped
# AND semantically valid as a date - day/month-first (DD/MM/YYYY,
# DD-MM-YYYY) or year-first (YYYY-MM-DD, YYYY/MM/DD) - with a full
# 4-digit year in a plausible calendar range. Requiring 4 digits (not
# 2-4) is what keeps this from reopening F6: a 6-digit sort-code-with-
# slashes bypass ("12/34/56") never has a 4-digit group, so the
# exemption is structurally unreachable for it. See redact() for why
# this can't safely extend to the 6-digit sort-code pattern too.
_ACCOUNT_NUMBER_RE = re.compile(r"\b\d(?:[-\s/]?\d){7}\b")

_DATE_LIKE_DAY_FIRST_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_DATE_LIKE_YEAR_FIRST_RE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")


def _is_plausible_date(day: int, month: int, year: int) -> bool:
    return 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2099


def _looks_like_an_unambiguous_date(span: str) -> bool:
    day_first = _DATE_LIKE_DAY_FIRST_RE.match(span)
    if day_first:
        day, month, year = (int(group) for group in day_first.groups())
        if _is_plausible_date(day, month, year):
            return True

    year_first = _DATE_LIKE_YEAR_FIRST_RE.match(span)
    if year_first:
        year, month, day = (int(group) for group in year_first.groups())
        if _is_plausible_date(day, month, year):
            return True

    return False

# Catch-all for an identifier the specific patterns above don't recognise:
# a contiguous run of 6+ digits that isn't part of a decimal amount. A
# 6- or 7-digit employee/payroll number falls in exactly this gap - too
# short for the 8-digit account pattern, no separators for the sort-code
# pattern - so it used to survive redact() untouched and then trip
# assert_safe_to_send's digit-run check, refusing the whole document.
#
# The gate was right to distrust it; the defect was that redact() left it
# in. Tokenising it here means the payslip still processes AND the number
# never leaves the process, instead of the previous outcome where it was
# only luck (the gate) that stopped it being sent.
#
# The lookbehind/lookahead keep this off legitimate money: "125000.00"
# has a 6-digit run, but it's followed by ".00" so it isn't matched, and
# ".123456" isn't matched because it's a decimal fraction. Comma-grouped
# amounts ("1,234,567") never have a 6+ contiguous run at all. Runs this
# long with no decimal point aren't any field in the extraction schema -
# every money field on a UK payslip prints to two decimal places.
_UNEXPLAINED_ID_RE = re.compile(r"(?<![\d.])\b\d{6,}\b(?!\.\d)")

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# UK phone number: leading 0 or +44, then 9-10 more digits with optional
# space/hyphen separators. The trailing (?!\.\d) stops it from matching
# the front of a decimal money amount that happens to start with a long
# digit run.
_PHONE_RE = re.compile(r"\b(?:\+44\s?|0)(?:\d[\s-]?){9,10}\b(?!\.\d)")

# Label-anchored: employee/works/payroll reference numbers. Captures the
# label in group 1 and the value in group 2 so redaction can keep the
# label (it's not personal on its own) and replace only the value.
_EMPLOYEE_NO_LABEL_RE = re.compile(
    r"(?im)\b(Works Number|Ref|Employee No\.?|Employee Number|Payroll No\.?)\s*:?\s*"
    r"([\w./-]+(?:\s*/\s*[\w./-]+)?)"
)

# Label-anchored name/address. Real payslips often DON'T label these at
# all (a name can just sit on its own line with a column header glued to
# it, e.g. "[NAME] Payments") - this only catches the labelled case.
# financial_lines_only() is what catches the unlabelled case, by dropping
# any line with no currency/date/percent/label content.
# [ \t] rather than \s: the value has to be on the SAME LINE as its label.
#
# \s matches \n, so "Name" alone on a line let \s* eat the line break and
# (.+)$ capture the whole of the NEXT line as the name. On a payslip that
# next line is routinely figures, so a bare "Name" header destroyed a row
# of pay data and welded it to the label - the same fault as the sort-code
# pattern, one field over. A label with no value beside it is a header, not
# a name.
_NAME_LABEL_RE = re.compile(r"(?im)^(Employee Name|Name)[ \t]*:?[ \t]*(.+)$")
# Same reasoning as _NAME_LABEL_RE above, and the same fix: the value must
# sit on the label's own line. "Address" as a bare header - which is how a
# multi-line address is usually printed - previously swallowed whichever
# line came next, and only the first of them.
_ADDRESS_LABEL_RE = re.compile(r"(?im)^(Address|Home Address)[ \t]*:?[ \t]*(.+)$")

# Words that end a name: payslip vocabulary, plus the company suffixes.
# Only consulted for the token AFTER a courtesy title, so this list
# doesn't have to be exhaustive - it has to stop the common collisions
# on a line where a name and a figure sit side by side.
_NAME_STOP_WORD = (
    r"PAYE|Tax|Pay|Payments|Deductions|Gross|Net|Total|National|Insurance|"
    r"NI|NIC|Pension|Student|Loan|Period|Code|Basic|Holiday|Holidays|Rate|"
    r"Hours|Earnings|Method|Dept|Ref|Ltd|Limited|PLC"
)

# Title-anchored employee name - the unlabelled case _NAME_LABEL_RE
# cannot see.
#
# financial_lines_only() was documented as the backstop for an
# unlabelled name, on the reasoning that a name line carries no
# financial content and so never survives the allowlist. A real payslip
# broke that: its identity row is
#
#     1195 Mr. K SAMPLE 13/02/2026 AB123456C
#
# - name, pay date and NI number on one collapsed row (see the module
# docstring on collapsed columns). The NI number was redacted, and the
# DATE then kept the whole line through the allowlist, carrying the
# employee's name to the model. The allowlist is a backstop for a name
# ALONE on a line, not for one sharing a line with a financial value -
# exactly the same ordering hazard the module docstring already
# describes for the NI number, one field over.
#
# A courtesy title is a genuine anchor, not a name-shaped guess: it is
# the one token on such a row that cannot be mistaken for a payslip
# figure or label. This does NOT try to find untitled names - see
# redact()'s docstring for that residual gap, which is real.
#
# Bounded deliberately: at most four following tokens, each capitalised
# and alphabetic (an initial, "O'Brien", "Smith-Jones"), and stopped by
# _NAME_STOP_WORD so "Mr J Smith PAYE Tax 0.00" gives up the name
# without swallowing the label beside it. Case-sensitive for the name
# tokens (scoped (?i:...) on the title only), so a lowercase word after
# a title can't extend the match.
_TITLED_NAME_RE = re.compile(
    r"\b(?i:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Rev)\b\.?"
    rf"(?:\s+(?!(?i:{_NAME_STOP_WORD})\b)[A-Z][A-Za-z'’-]*\.?){{1,4}}"
)

# Colon required (unlike the name/address labels below) - "Employer" on
# its own is too common a prefix on a real payslip ("Employer NIC 24.98"
# is the employer's own NI contribution, not a name label) to match
# without one.
_EMPLOYER_LABEL_RE = re.compile(r"(?im)^(Employer|Company|Trading as)\s*:\s*(.+)$")


def _find_employer_name(text: str, redaction_map: RedactionMap) -> Optional[str]:
    """
    Employer name, kept locally (never sent - see redact()). Label-
    anchored only ("Employer:", "Company:", "Trading as:" - colon
    required, same reasoning as the "Employer NIC" collision noted on
    _EMPLOYER_LABEL_RE below).

    There is deliberately no fallback to "the first line of the
    document" here. That heuristic used to exist, and on a live run
    against five real payslips it returned the EMPLOYEE's own name on
    two of them, and an unexplained reference code on the other three -
    zero out of five correct. Whichever text happens to sit first in a
    payslip's layout varies by employer and is not reliably the company
    name. A null here is honest; a guess that lands on someone's own
    name breaks the one promise this pipeline makes about personal data,
    which is worse than an absent field.
    """
    match = _EMPLOYER_LABEL_RE.search(text)
    if not match:
        return None

    candidate = match.group(2).strip()

    # Guard: reject a candidate that is actually a piece of PII this
    # same pass already found elsewhere in the document - most
    # importantly the employee's own name. redaction_map.replacements is
    # only populated by the substitution passes above, so this must run
    # after them (see call site in redact()).
    already_redacted_values = {
        value for values in redaction_map.replacements.values() for value in values
    }
    if candidate in already_redacted_values:
        return None

    return candidate


def _redact_pattern(
    text: str,
    pattern: re.Pattern[str],
    token: str,
    redaction_map: RedactionMap,
    *,
    skip_if=None,
) -> str:
    """Replace every whole match of `pattern` with `token`.

    `skip_if`, if given, is called with the matched text; a True result
    leaves that match untouched instead of redacting it. Used to exempt
    a payslip date that happens to share a bank pattern's digit shape -
    see _looks_like_an_unambiguous_date().
    """

    def _sub(match: re.Match[str]) -> str:
        if skip_if is not None and skip_if(match.group(0)):
            return match.group(0)
        redaction_map.record(token, match.group(0))
        return token

    return pattern.sub(_sub, text)


def _redact_labelled(
    text: str, pattern: re.Pattern[str], token: str, redaction_map: RedactionMap
) -> str:
    """Replace only the value half (group 2) of a labelled match, keeping
    the label (group 1) so the line still reads sensibly."""

    def _sub(match: re.Match[str]) -> str:
        redaction_map.record(token, match.group(2))
        return f"{match.group(1)} {token}"

    return pattern.sub(_sub, text)


def redact(text: str) -> tuple[str, RedactionMap]:
    """
    Replace PII with tokens ([NAME], [NI], [ADDRESS], [EMPLOYEE_NO],
    [BANK], [EMAIL], [PHONE], [NUMBER]) rather than deleting it - layout
    matters, and a deleted span would just shift everything after it.

    Must run before financial_lines_only(). See the module docstring for
    why: a line can carry both PII and a currency amount together.

    KNOWN RESIDUAL GAP, stated plainly because the allowlist is no longer
    a complete backstop for it (see _TITLED_NAME_RE): a name that is
    neither labelled ("Employee Name:") nor titled ("Mr", "Ms") and that
    shares a line with a currency amount or date still reaches the
    model. "K SAMPLE 13/02/2026" on one row would not be caught here.
    Closing that needs a name detector, and every name-shaped heuristic
    tried in this file so far has been wrong more often than right (see
    _find_employer_name) - a wrong guess here redacts a financial label
    and breaks extraction. Flagged rather than patched over.
    """
    redaction_map = RedactionMap()
    redacted = text

    # Order matters here too: NI number and postcode are the most
    # specific patterns (least likely to over-match), so they run before
    # the looser 8-digit account number check gets a chance at the same
    # digits.
    redacted = _redact_pattern(redacted, _NI_NUMBER_RE, "[NI]", redaction_map)
    redacted = _redact_pattern(redacted, _POSTCODE_RE, "[ADDRESS]", redaction_map)
    # Sort code has no date exemption: a 6-digit DD/MM/YY date and a real
    # sort-code-with-slashes bypass (F6) are the same shape, and telling
    # them apart would need the same day/month plausibility check that
    # already can't reliably distinguish a coincidental sort code from a
    # real date (a sort code's digits aren't meaningfully "random" in a
    # way that rules out a day-1-31/month-1-12-shaped one). Payslips
    # overwhelmingly print 4-digit years, so this residual gap - an
    # uncommon 2-digit-year date getting redacted as a sort code - is the
    # safer default over reopening F6.
    redacted = _redact_pattern(redacted, _SORT_CODE_RE, "[BANK]", redaction_map)
    redacted = _redact_pattern(
        redacted,
        _ACCOUNT_NUMBER_RE,
        "[BANK]",
        redaction_map,
        skip_if=_looks_like_an_unambiguous_date,
    )
    redacted = _redact_pattern(redacted, _EMAIL_RE, "[EMAIL]", redaction_map)
    redacted = _redact_pattern(redacted, _PHONE_RE, "[PHONE]", redaction_map)
    redacted = _redact_labelled(redacted, _EMPLOYEE_NO_LABEL_RE, "[EMPLOYEE_NO]", redaction_map)
    redacted = _redact_labelled(redacted, _NAME_LABEL_RE, "[NAME]", redaction_map)
    # After the labelled pass, so a labelled "Name: Mr K Onuoha" is
    # already gone and this only sees the unlabelled rows. See
    # _TITLED_NAME_RE.
    redacted = _redact_pattern(redacted, _TITLED_NAME_RE, "[NAME]", redaction_map)
    redacted = _redact_labelled(redacted, _ADDRESS_LABEL_RE, "[ADDRESS]", redaction_map)

    # Last of the value passes, deliberately: every pattern above is more
    # specific and gets first claim on the same digits, so this only sees
    # what none of them recognised. See _UNEXPLAINED_ID_RE.
    redacted = _redact_pattern(redacted, _UNEXPLAINED_ID_RE, "[NUMBER]", redaction_map)

    # Runs last and reads the ORIGINAL text, not `redacted` - it needs to
    # see real label text ("Employer:"), and its own guard needs
    # redaction_map already populated by the passes above.
    redaction_map.employer_name = _find_employer_name(text, redaction_map)

    return redacted, redaction_map


# ==========================================================================
# Allowlist filter
# ==========================================================================

_CURRENCY_RE = re.compile(r"£?\d[\d,]*\.\d{2}\b")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s?%")
_MONTH_NAMES = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# [- \t] rather than [-\s] in the month-name alternative: a date does not
# span a line break, and here that mattered in the UNSAFE direction.
#
# _DATE_RE has two jobs. financial_lines_only() calls it per line, so a
# cross-line match was impossible there. But _mask_known_safe_numbers()
# runs it over the WHOLE payload with .sub(" "), to remove digits that a
# payslip legitimately explains before the gate looks for unexplained ones.
# With \s it could match across a newline and mask the last group of a
# group-printed digit sequence:
#
#     Code 123 4567 89
#     Mar 2026 National Insurance 0.00
#
# "89\nMar 2026" masked away leaves "Code 123 4567", two groups instead of
# three, so _SPLIT_DIGIT_GROUPS_RE no longer fires and the gate passes a
# payload it refuses when the same digits sit on one line. Four such
# sequences were found by search; each evades redact(), is caught by the
# gate's second check alone, and is released by a month name on the
# following line.
#
# The two numeric alternatives below use [/-] and were never affected.
_DATE_RE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?[- \t](?:{_MONTH_NAMES})[a-z]*[- \t]\d{{2,4}}\b"
    rf"|\b\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}\b"
    # Year-first / ISO (YYYY-MM-DD). Without this alternative, an ISO
    # pay date has no financial shape this pattern recognises: the
    # allowlist (financial_lines_only, below) would drop a line whose
    # only content is an ISO date, and assert_safe_to_send's digit-run
    # check (_mask_known_safe_numbers) would flag the same date's
    # leftover digits as unexplained and refuse a payload that's
    # already safe - which is exactly what _looks_like_an_unambiguous_
    # date's ISO branch fixed for account-number redaction, but this is
    # a separate regex that needed the same fix independently.
    rf"|\b\d{{4}}[/-]\d{{1,2}}[/-]\d{{1,2}}\b",
    re.IGNORECASE,
)
_TAX_CODE_LINE_RE = re.compile(
    r"\b[SC]?\d{1,4}[LMNPTY]\b|\b[SC]?(?:BR|D0|D1|0T|NT)\b|\b[SC]?K\d{1,4}\b",
    re.IGNORECASE,
)
_KNOWN_LABEL_RE = re.compile(
    r"(?i)\b("
    r"tax code|gross|net pay|national insurance|nic|paye|income tax|"
    r"pension|student loan|postgraduate loan|pgl|"
    r"year to date|ytd|hours|rate|"
    r"pay(?:ment)? period|pay date|tax period|tax month|tax week|period number|"
    r"frequency|pay type|pay basis|"
    r"ni category|ni table|table letter"
    r")\b"
)
# Deliberately excludes generic section headers like "Deductions" and
# "Payments": a real payslip's unlabelled name line ("[NAME] Payments")
# would otherwise survive the filter on the word "Payments" alone - the
# whole point of the allowlist is that a bare header with no figure
# attached gets dropped, PII or not.
#
# Audited 2026-08 against every field _ModelExtract can report (not just
# the one gap that was reported): frequency/pay type/pay basis and
# tax period/tax month/tax week/period number were all missing entirely -
# a payslip stating its period as "Tax Period Month 9" or its basis as
# "Pay Frequency Monthly" on a line with no currency figure had that
# context silently dropped before the model ever saw it. Same problem
# for ni_category ("NI Table Letter A" contains neither "national
# insurance" nor "nic" as a substring) and student_loan_plan
# ("Postgraduate Loan" doesn't contain "student loan").
#
# "pay(ment)? period" rather than "pay period", same class of gap, found
# on a real weekly payslip: the document stated its frequency exactly
# once, as "Payment Period    Weekly", on a line carrying no currency
# amount, date, percentage or tax code. "Payment Period" does not
# contain "pay period" as a substring, so that line was dropped before
# the model or infer_frequency_from_label() ever saw it - leaving
# frequency null, period_number underivable, and every calculation
# skipped behind "We could not complete every calculation", on a payslip
# that printed both its frequency and its period number in plain text.


def financial_lines_only(text: str) -> str:
    """
    Allowlist filter: keep a line only if it contains a currency amount,
    a percentage, a date, a tax-code pattern, or a known payslip label.
    Everything else is dropped unseen.

    This is the primary privacy control, not a secondary one. It catches
    whatever the redaction regexes above missed - most importantly an
    unlabelled name or address line, which has no shape a PII regex can
    anchor to but also has no financial content, so it never survives
    this filter.

    That last claim holds only for a name ALONE on its line. It used to
    be written here as though it held for any unlabelled name, and a
    real payslip disproved that: "1195 Mr. K SAMPLE 13/02/2026
    AB123456C" is one collapsed row, and the date alone is enough to
    keep it - name included. Redaction, not this filter, is what has to
    catch a name sharing a line with a financial value; see
    _TITLED_NAME_RE and redact()'s stated residual gap.

    Must run AFTER redact(). See the module docstring for why.
    """
    kept = [
        line
        for line in text.splitlines()
        if _CURRENCY_RE.search(line)
        or _PERCENT_RE.search(line)
        or _DATE_RE.search(line)
        or _TAX_CODE_LINE_RE.search(line)
        or _KNOWN_LABEL_RE.search(line)
    ]
    return "\n".join(kept)


# ==========================================================================
# Final gate
# ==========================================================================

_PII_RECHECK_PATTERNS: tuple[tuple[str, re.Pattern[str], object], ...] = (
    ("NI number", _NI_NUMBER_RE, None),
    ("postcode", _POSTCODE_RE, None),
    ("sort code", _SORT_CODE_RE, None),
    # Same exemption as redact() - see _looks_like_an_unambiguous_date()
    # and the comment on _ACCOUNT_NUMBER_RE. This check re-scans with
    # the same shaped patterns redact() uses, so it must apply the same
    # exemption redact() does - otherwise a date that correctly survives
    # redact() gets refused here anyway, on a payload that was already
    # safe to send.
    ("account number", _ACCOUNT_NUMBER_RE, _looks_like_an_unambiguous_date),
    ("email", _EMAIL_RE, None),
    ("phone", _PHONE_RE, None),
    # Shares redact()'s regex, like every entry above it, so it adds no
    # independent detection power - what it adds is failing CLOSED if
    # this pattern ever stops running in redact() (a reordering, an
    # early return): the payload is refused instead of quietly sent with
    # a name in it. Check 2 below cannot see a name at all - it only
    # reasons about unexplained digits - so without this entry a name is
    # the one PII class the gate has no opinion on whatsoever.
    ("name", _TITLED_NAME_RE, None),
)


def _has_unexempted_match(pattern: re.Pattern[str], payload: str, skip_if) -> bool:
    for match in pattern.finditer(payload):
        if skip_if is not None and skip_if(match.group(0)):
            continue
        return True
    return False

# A run of 6 or more digits WITHIN ONE TOKEN - whitespace deliberately
# not tolerated here, unlike the structured-number patterns above. Used
# only as the SECOND, independent check in assert_safe_to_send() - see
# there for why.
#
# Whitespace used to be in this class, which made the check count digits
# across independent, adjacent numbers and refuse entirely benign lines:
# "Period 09 2025" reads as a 6-digit run ("09 2025") though it's just a
# period number beside a year. That produced a live 422 on a real
# payslip. Space-separated PII is not lost by this: a sequence of
# uniform digit groups is caught by _SPLIT_DIGIT_GROUPS_RE below, and
# every space-separated PII shape the pipeline knows (NI number, sort
# code, account number, phone) is independently caught by check 1.
_UNEXPLAINED_DIGIT_RUN_RE = re.compile(r"(?:\d[./-]*){6,}")

# The space-separated half of the same check: three or more groups of 2-4
# digits in a row, each separated by a single space, totalling 6+ digits.
# That is what PII looks like when it's printed in groups ("44 99 43",
# "1234 5678 9012") and is a shape no legitimate payslip figure takes -
# a payslip prints amounts as single tokens, not as uniform digit
# groups. Requiring 3+ groups is what keeps "Period 09 2025" (two
# groups, and not uniform) from matching.
_SPLIT_DIGIT_GROUPS_RE = re.compile(r"\b\d{2,4}(?: \d{2,4}){2,}\b")

# Any decimal number, to any precision - masking only, never used to
# decide what the allowlist KEEPS (that's _CURRENCY_RE, which requires
# exactly two decimal places and is deliberately left narrow: widening
# it would widen what gets sent). Hourly rates are routinely printed to
# 3-5 decimal places ("Rate 15.3846"), which _CURRENCY_RE doesn't match,
# so those digits used to survive masking and read as an unexplained
# run - the other half of the same live 422.
_MASKABLE_DECIMAL_RE = re.compile(r"\b\d[\d,]*\.\d{1,6}\b")


def _mask_known_safe_numbers(text: str) -> str:
    """Strip every span that legitimately explains a run of digits on a
    payslip line, leaving only what neither the allowlist nor a normal
    payslip figure accounts for."""
    masked = _CURRENCY_RE.sub(" ", text)
    masked = _PERCENT_RE.sub(" ", masked)
    masked = _DATE_RE.sub(" ", masked)
    masked = _TAX_CODE_LINE_RE.sub(" ", masked)
    masked = _MASKABLE_DECIMAL_RE.sub(" ", masked)
    return masked


def assert_safe_to_send(payload: str) -> None:
    """
    Final gate, immediately before the API call. Fails closed: if this
    raises, the caller must not send the payload anyway.

    Two independent checks, not one:

    1. Re-scans with the same shaped patterns redact() uses. This catches
       PII that survives on an otherwise-legitimate line - e.g. an NI
       number sitting next to a currency amount, which the allowlist
       keeps for the currency amount alone (see the module docstring for
       why redact() must run before financial_lines_only()).

    2. Masks out every recognised-safe numeric shape (currency, percent,
       date, tax code, any-precision decimal) and refuses if what's left
       contains either 6+ digits inside a single token, or three or more
       uniform digit groups in a row. This doesn't know what an NI
       number, sort code or account number looks like, so it can't share
       check 1's blind spot for a shape neither regex set recognises yet
       - it catches by the ABSENCE of an explanation for a run of
       digits, not by recognising a specific kind of personal data.
       "Two labels on one control" is exactly what this function used to
       be with only check 1.

       The two halves of check 2 exist because whitespace is genuinely
       ambiguous here: it separates PII printed in groups ("44 99 43")
       and equally separates unrelated payslip numbers that just happen
       to sit next to each other ("Period 09 2025"). Treating it as an
       intra-number separator refused benign payslips; ignoring it
       entirely would miss group-printed PII. Splitting the check keeps
       both.

    Deliberately does not include the matched text in the exception
    message - the point of this function is to stop PII leaving the
    process, so it must not leak it into a log line instead.
    """
    for label, pattern, skip_if in _PII_RECHECK_PATTERNS:
        if _has_unexempted_match(pattern, payload, skip_if):
            raise RedactionFailure(f"payload still matches a PII pattern: {label}")

    masked = _mask_known_safe_numbers(payload)

    if _UNEXPLAINED_DIGIT_RUN_RE.search(masked):
        raise RedactionFailure(
            "payload has an unexplained run of digits with no financial shape"
        )

    if _SPLIT_DIGIT_GROUPS_RE.search(masked):
        raise RedactionFailure(
            "payload has an unexplained sequence of digit groups"
        )


# ==========================================================================
# PDF reading
# ==========================================================================


def _read_pdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Shared by extract_text() and extract_payslip() so a PDF is only
    ever parsed once. Never uses extract_tables() - confirmed against
    five real payslips that it returns rows of empty strings on all of
    them (ruled lines, not tagged table structure)."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise UnreadableDocument("no text layer found in PDF")
    return text, len(pages)


def extract_text(pdf_bytes: bytes) -> str:
    """pdfplumber, entirely in memory (BytesIO) - never writes to disk."""
    text, _pages = _read_pdf(pdf_bytes)
    return text


# ==========================================================================
# Model-facing schema
# ==========================================================================
#
# A deliberate subset of PayslipExtract, not the whole thing. `source` is
# about the file, not the document's contents, so the model never sees
# it. `reconciles` must be computed in code, never self-reported, so it
# isn't in this schema either - there is no field for the model to fill
# in even if it wanted to guess.


class _ModelPeriod(BaseModel):
    """Same shape as contract.Period, minus tax_year. tax_year is always
    derived from pay_date in code (see _tax_year_for) - excluding it here
    means there's no stale/model-guessed value to accidentally trust."""

    pay_date: Optional[date] = None
    period_number: Optional[int] = None
    frequency: Optional[Frequency] = None


class _ModelExtract(BaseModel):
    is_payslip: bool = Field(
        True, description="False if this document is not a payslip at all."
    )
    employer_name: Optional[str] = None
    period: _ModelPeriod = Field(default_factory=_ModelPeriod)
    tax_code: TaxCodeRead = Field(default_factory=TaxCodeRead)
    pay: Pay = Field(default_factory=Pay)
    deductions: Deductions = Field(default_factory=Deductions)
    net_pay: Optional[Decimal] = None
    confidence: dict[str, float] = Field(default_factory=dict)
    unreadable_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Full dotted paths of any fields you were genuinely "
            "uncertain about - where the document was contradictory, "
            "unlabelled, or you had to choose between competing "
            "candidate values. Do not list a field merely because you "
            "added an explanatory note about it."
        ),
    )
    warnings: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You read UK payslips and report exactly what is printed. You never \
calculate anything - no tax, no totals, no checks. Code does that \
afterwards.

The text below has already been through a privacy filter: personal \
details are replaced with tokens like [NAME] and [NI], and lines with no \
financial content have been dropped. Some context may be missing as a \
result - that is expected. Report what you can still read.

Layout warning: this is a flattened two-column payslip. A label and its \
value can be separated, on the same line, by unrelated text belonging to \
another column, e.g.:

    Tax Code 1257L Income Tax 0.00
    NI Number [NI] National Insurance 0.00

Read carefully - the value immediately after a label belongs to THAT \
label, not to whatever comes right after it.

Rules:
- If the document is not a payslip, set is_payslip to false and leave \
  everything else at its default.
- "National Insurance" / "NIC" on its own means the EMPLOYEE figure. If \
  both an employee and an employer NI figure are shown, take the \
  employee one only - never the employer figure.
- "Year to Date" / "YTD" figures are cumulative for the tax year so far. \
  Keep them separate from this pay period's own figures.
- period.frequency: a printed period label is enough to read this from - \
  "Month 9" / "Tax Month 9" means monthly, "Week 39" / "Tax Week 39" \
  means weekly. You do not need the literal word "Monthly" on the page. \
  Do NOT infer it from the pay date alone, and return null if the \
  payslip says only "Period 9" without naming the unit, or names a \
  frequency that is neither monthly nor weekly (fortnightly, 4-weekly, \
  quarterly).
- Report a confidence score from 0 to 1 for every field you fill in, \
  keyed by dotted path (e.g. "pay.gross_this_period"). If you are not \
  confident, return null for that field rather than guessing - a \
  missing figure is fine, a wrong one is not.
- Every entry in unreadable_fields, and every key in confidence, must be \
  the FULL dotted path from the root of the schema, e.g. \
  "deductions.student_loan" - never just "student_loan".
- Use warnings for anything worth explaining even when you ARE \
  confident (e.g. naming an emergency tax code). Only use \
  ambiguous_fields for a field you had to guess at or choose between \
  competing values for - not every field you left a note about belongs \
  there.
"""

# Which LLM provider does the extraction call. "anthropic" (default) or
# "openai" - deliberately a separate setting from the model name, and
# deliberately validated at import time (fails loudly on startup, not on
# the first real upload during a demo).
_MODEL_PROVIDER = os.environ.get("SLYP_MODEL_PROVIDER", "anthropic").strip().lower()

if _MODEL_PROVIDER not in ("anthropic", "openai"):
    raise ValueError(
        f"Unsupported SLYP_MODEL_PROVIDER: {_MODEL_PROVIDER!r}. "
        f"Expected 'anthropic' or 'openai'."
    )

if _MODEL_PROVIDER == "anthropic":
    # Overridable via env var so this can be changed without a code
    # deploy; the default is a placeholder pick, not a benchmarked
    # choice - revisit once real extractions have been checked for
    # accuracy against the sample payslips.
    _MODEL_NAME = os.environ.get("SLYP_EXTRACTION_MODEL", "claude-sonnet-5")
else:
    # No default here, deliberately: a Claude model name is not a valid
    # guess for an OpenAI model and vice versa, so there's no safe
    # fallback to invent for a provider switch. Must be set explicitly.
    _MODEL_NAME = os.environ.get("SLYP_EXTRACTION_MODEL")
    if not _MODEL_NAME:
        raise ValueError(
            "SLYP_EXTRACTION_MODEL must be set when "
            "SLYP_MODEL_PROVIDER=openai."
        )

def required_credential_name() -> str:
    """
    The environment variable that must hold an API key for whichever
    provider SLYP_MODEL_PROVIDER selected.

    Exists so the API layer can refuse to start without one, rather than
    booting healthy and failing on the first upload. Deliberately derived
    from the resolved _MODEL_PROVIDER above rather than re-reading the
    environment, so the two can never disagree about which provider is in
    play - which is the whole failure mode being guarded against.

    The check itself is NOT made here, at import time: this module is
    imported by the test suite, which has no reason to hold a real key.
    main.py owns the refusal. See there.
    """
    return "OPENAI_API_KEY" if _MODEL_PROVIDER == "openai" else "ANTHROPIC_API_KEY"


logger = logging.getLogger(__name__)

# Learned on the first call and reused for the rest of the process - see
# the retry in _call_openai_model(). Per-process, so each uvicorn worker
# pays the discovery round trip once.
_OPENAI_NEEDS_REASONING_EFFORT_NONE = False

_TOOL_NAME = "record_payslip_extract"

# Below this, a field is not trusted even if the model didn't flag it
# itself - self-reported confidence is a signal, not a measurement (see
# contract.PayslipExtract.confidence). Placeholder threshold, not tuned
# against real extractions yet.
_CONFIDENCE_THRESHOLD = 0.7


def _call_model(filtered_text: str) -> _ModelExtract:
    """
    Dispatches to whichever provider SLYP_MODEL_PROVIDER selects. Both
    paths force a structured tool/function call against the exact same
    _ModelExtract schema and _SYSTEM_PROMPT, so nothing downstream
    (normalisation, confidence thresholding, reconciliation) needs to
    know or care which provider actually answered.
    """
    if _MODEL_PROVIDER == "openai":
        return _call_openai_model(filtered_text)
    return _call_anthropic_model(filtered_text)


def _call_anthropic_model(filtered_text: str) -> _ModelExtract:
    # anthropic.Anthropic() reads ANTHROPIC_API_KEY from the environment
    # on its own - no key is read or passed here, so there is nowhere in
    # this file for one to leak from.
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_MODEL_NAME,
        max_tokens=2048,
        temperature=0,
        system=_SYSTEM_PROMPT,
        tools=[
            {
                "name": _TOOL_NAME,
                "description": "Record the structured fields read off a UK payslip.",
                "input_schema": _ModelExtract.model_json_schema(),
            }
        ],
        # Forces the tool call so the response can only be shaped like
        # _ModelExtract - there is no free-text path for the model to
        # answer through instead.
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": filtered_text}],
    )

    tool_use = next(
        (block for block in response.content if block.type == "tool_use"), None
    )
    if tool_use is None:
        raise NotAPayslip("model returned no structured output")

    try:
        return _ModelExtract.model_validate(tool_use.input)
    except ValidationError as exc:
        raise NotAPayslip(f"model output did not match the extraction schema: {exc}") from exc


def _call_openai_model(filtered_text: str) -> _ModelExtract:
    # openai.OpenAI() reads OPENAI_API_KEY from the environment on its
    # own, same reasoning as the Anthropic path above - and deliberately
    # a different env var name from ANTHROPIC_API_KEY. Putting one
    # provider's key under the other provider's variable name is exactly
    # how this integration broke the first time.
    client = openai.OpenAI()

    def _create(**extra_params):
        return client.chat.completions.create(
            model=_MODEL_NAME,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": filtered_text},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": _TOOL_NAME,
                        "description": "Record the structured fields read off a UK payslip.",
                        "parameters": _ModelExtract.model_json_schema(),
                    },
                }
            ],
            # Forces the tool call, same reasoning as the Anthropic path:
            # no free-text path for the model to answer through instead.
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
            **extra_params,
        )

    global _OPENAI_NEEDS_REASONING_EFFORT_NONE

    try:
        response = _create(
            **({"reasoning_effort": "none"} if _OPENAI_NEEDS_REASONING_EFFORT_NONE else {})
        )
    except openai.BadRequestError as exc:
        # Some reasoning-capable models reject a tool call unless
        # reasoning_effort is explicitly turned off for it. Confirmed
        # live against gpt-5.6-sol, which answers:
        #
        #   "Function tools with reasoning_effort are not supported for
        #    gpt-5.6-sol in /v1/chat/completions. To use function tools,
        #    use /v1/responses or set reasoning_effort to 'none'."
        #
        # Nothing in the request is malformed - the parameter it names,
        # reasoning_effort, is one we never sent. The model applies its
        # own default, and function tools are unsupported alongside it.
        #
        # Still not sent unconditionally: a model that doesn't recognise
        # the parameter at all would then fail every call instead of
        # none. But the answer doesn't change between calls, so it's
        # remembered for the life of the process - otherwise every single
        # upload pays a doomed round trip first (~2s, and it was showing
        # up as a 400 in the logs on every request).
        if "reasoning_effort" in str(exc) and not _OPENAI_NEEDS_REASONING_EFFORT_NONE:
            _OPENAI_NEEDS_REASONING_EFFORT_NONE = True
            logger.info(
                "openai: model requires reasoning_effort='none' for function "
                "tools; retrying and remembering for this process"
            )
            response = _create(reasoning_effort="none")
        else:
            raise

    tool_calls = response.choices[0].message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == _TOOL_NAME), None)

    if tool_call is None:
        raise NotAPayslip("model returned no structured output")

    try:
        arguments = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as exc:
        raise NotAPayslip(f"model output was not valid JSON: {exc}") from exc

    try:
        return _ModelExtract.model_validate(arguments)
    except ValidationError as exc:
        raise NotAPayslip(f"model output did not match the extraction schema: {exc}") from exc


# ==========================================================================
# Post-processing: everything the model is never trusted with
# ==========================================================================


def _tax_year_start(pay_date: date) -> date:
    """The 6 April on or before `pay_date` - the start of its UK tax
    year. Shared by _tax_year_for() and derive_period_number() so the
    boundary logic exists in exactly one place."""
    boundary = date(pay_date.year, 4, 6)
    return boundary if pay_date >= boundary else date(pay_date.year - 1, 4, 6)


def _tax_year_for(pay_date: date) -> str:
    """
    UK tax years run 6 April to 5 April: 31-Mar-2026 is in 2025/26, but
    06-Apr-2026 is in 2026/27. Always derived from the pay date here -
    the model is never asked for this, because getting the boundary day
    wrong is an easy, silent, once-a-year mistake to make.
    """
    start = _tax_year_start(pay_date)
    return f"{start.year}/{(start.year + 1) % 100:02d}"


def derive_period_number(
    pay_date: Optional[date], frequency: Optional[Frequency]
) -> Optional[int]:
    """
    Pure arithmetic from the pay date and frequency - never asked of the
    model. The cumulative income tax calculation needs this (allowance
    used so far = annual allowance * period_number / periods in year),
    so a null here silently breaks most of what the product does; it is
    worth deriving even when the model already supplied a value, and
    preferring the derived one if they disagree.

    Monthly: month 1 runs 6 April to 5 May, month 2 runs 6 May to 5 June,
    and so on. Computed as whole calendar months elapsed since the tax
    year's start month, minus one if `pay_date` falls before day 6 (day
    1-5 still belongs to the previous month's bucket).

    Weekly: week 1 begins on the tax year start date (6 April) and every
    7 days is another week. A UK tax year (365 or 366 days) is not an
    exact multiple of 7, so the last few days fall in week 53 - that is
    returned as-is, not clamped to 52.
    """
    if pay_date is None or frequency is None:
        return None

    start = _tax_year_start(pay_date)

    if frequency == "monthly":
        months_elapsed = (pay_date.year * 12 + pay_date.month) - (
            start.year * 12 + start.month
        )
        if pay_date.day < 6:
            months_elapsed -= 1
        return months_elapsed + 1

    days_elapsed = (pay_date - start).days
    return days_elapsed // 7 + 1


# Valid period_number range per frequency - used only by the printed-
# period-label fallback below, to reject an implausible combination
# (e.g. "period 45" against a monthly payslip) rather than accept
# anything the model reports once frequency is confirmed.
_PERIOD_NUMBER_RANGE: dict[str, range] = {
    "monthly": range(1, 13),
    "weekly": range(1, 54),
}


def _period_number_plausible(period_number: int, frequency: Optional[Frequency]) -> bool:
    valid_range = _PERIOD_NUMBER_RANGE.get(frequency or "")
    return valid_range is not None and period_number in valid_range


# Frequency read from a printed period label. Plenty of payslips never
# print the word "Monthly" anywhere - they print "Month 9" or "Tax Month
# 9" - and the prompt tells the model to return null rather than guess,
# so it correctly returns nothing. Without a frequency, period_number
# can't be derived, and without period_number the whole calculation is
# skipped: that surfaces as "We could not complete every calculation".
#
# Reading the word "Month" beside a number is extraction, the same
# operation already trusted for the tax code - not the model inventing a
# value. Done in code rather than left to the model so it's
# deterministic and testable without an API call.
#
# Requires a DIGIT after the word, so "Week Ending 15/12/2025" (a date
# label, no period number) doesn't read as weekly.
_MONTHLY_LABEL_RE = re.compile(
    r"(?i)\bmonthly\b|\b(?:tax\s+)?month\s*(?:no\.?|number|:)?\s*\d{1,2}\b"
)
_WEEKLY_LABEL_RE = re.compile(
    r"(?i)\bweekly\b|\b(?:tax\s+)?week\s*(?:no\.?|number|:)?\s*\d{1,2}\b"
)

# Frequencies the engine has no rates or period maths for. If any of
# these appear, refuse to infer at all rather than let the bare word
# "weekly" inside "4-weekly" or "bi-weekly" read as plain weekly - that
# would silently calculate a 4-weekly payslip on weekly thresholds.
_UNSUPPORTED_FREQUENCY_RE = re.compile(
    r"(?i)\b(?:fortnight(?:ly)?|bi[-\s]?weekly|(?:2|two|4|four)[-\s]?weekly|"
    r"quarterly|annual(?:ly)?|yearly|daily)\b"
)


# Pay date read from its printed label. Same motivation as
# infer_frequency_from_label(): pay_date drives period_number, which
# gates the whole calculation, and leaving it solely to the model makes
# the result non-deterministic - the same payslip intermittently loses
# the field and the user sees "We could not complete every calculation"
# on some runs and not others, with temperature already pinned to 0.
#
# Label-anchored deliberately. A payslip carries several dates - period
# start and end, continuous service date, tax year dates - and an
# unanchored "first date on the page" read would confidently pick the
# wrong one. That's the wrong-value failure this pipeline exists to
# avoid, and it's worse than a missing field.
_PAY_DATE_LABEL_RE = re.compile(
    r"(?i)\b(?:pay\s*(?:ment)?\s*d(?:ate|ay)|date\s+paid)\b[^\n\d]{0,20}?("
    rf"\d{{1,2}}(?:st|nd|rd|th)?[-\s/](?:{_MONTH_NAMES})[a-z]*[-\s/]\d{{2,4}}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}[/-]\d{1,2}[/-]\d{1,2}"
    r")"
)

_MONTH_NUMBER = {
    name.lower(): index
    for index, name in enumerate(_MONTH_NAMES.split("|"), start=1)
}


def _parse_labelled_date(raw: str) -> Optional[date]:
    """Parse the date shapes _PAY_DATE_LABEL_RE captures, or None.

    Day-first for the all-numeric forms: this is a UK payslip, where
    05/06/2025 is 5 June. A two-digit year is read as 2000-2099 - a
    payslip is a current document, not a historical one.
    """
    cleaned = re.sub(r"(?i)(\d)(st|nd|rd|th)", r"\1", raw.strip())
    parts = re.split(r"[-\s/]+", cleaned)
    if len(parts) != 3:
        return None

    try:
        if parts[0].isdigit() and len(parts[0]) == 4:  # ISO, year first
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        elif parts[1].isdigit():  # all numeric, day first
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        else:  # "15 Dec 2025"
            month_number = _MONTH_NUMBER.get(parts[1][:3].lower())
            if month_number is None:
                return None
            day, month, year = int(parts[0]), month_number, int(parts[2])
    except ValueError:
        return None

    if year < 100:
        year += 2000

    try:
        return date(year, month, day)
    except ValueError:  # e.g. 31 February
        return None


def read_pay_date_from_label(text: str) -> Optional[date]:
    """
    Pay date read from an explicit "Pay Date"/"Pay Day"/"Payment Date"/
    "Date Paid" label, or None.

    Returns None - never a guess - when no labelled date is found, when
    one is found but doesn't parse to a real calendar date, or when two
    labelled pay dates disagree. A disagreement means the layout isn't
    what this assumes, which is exactly when picking one would be wrong.
    """
    found = {
        parsed
        for parsed in (
            _parse_labelled_date(match.group(1))
            for match in _PAY_DATE_LABEL_RE.finditer(text)
        )
        if parsed is not None
    }
    return found.pop() if len(found) == 1 else None


def infer_frequency_from_label(text: str) -> Optional[Frequency]:
    """
    Frequency from an explicitly printed period label, or None.

    Returns None - never a guess - when the evidence is absent,
    contradictory (both a month and a week label), or names a frequency
    the engine doesn't support. "Period 9" on its own is deliberately
    not enough: it doesn't say which unit, and picking one would be
    exactly the invented-value failure this pipeline exists to avoid.
    """
    if _UNSUPPORTED_FREQUENCY_RE.search(text):
        return None

    monthly = _MONTHLY_LABEL_RE.search(text) is not None
    weekly = _WEEKLY_LABEL_RE.search(text) is not None

    if monthly and not weekly:
        return "monthly"
    if weekly and not monthly:
        return "weekly"
    return None


# Best-effort validation of the tax code shapes types.TaxCodeKind
# recognises. A code failing this doesn't raise - it just means
# tax_code.value goes into unreadable_fields like any other suspect
# field, per "a missing field is fine, a wrong field is not."
# A previous-employment year-to-date line: the P45 carry-forward a payroll
# system prints when someone joined part-way through the tax year. Its
# presence means this payslip's YTD column is NOT the whole tax year, which
# is decisive for the allowance-used figure (see
# analysis.build_allowance_usage) - direct documentary evidence beats
# whatever the user answered about other employment.
#
# Read in code rather than asked of the model, for the same reason
# reconciles and tax_year are: it decides whether a figure is shown at all,
# so it must be deterministic. Matched against the REDACTED text before the
# allowlist filter runs, because a bare "Previous Employment" header
# carrying no currency amount would be dropped by the allowlist - and the
# header alone is still evidence.
_PREVIOUS_EMPLOYMENT_RE = re.compile(
    r"(?i)\b("
    r"previous\s+employ(?:ment|er)|prev\.?\s+employ(?:ment|er)|"
    r"pay\s+from\s+previous|previous\s+pay|previous\s+taxable\s+pay|"
    r"p45|brought\s+forward|b/?fwd|"
    r"(?:gross|taxable\s+pay|tax)\s+(?:in\s+)?previous\s+employment"
    r")\b"
)


def has_previous_employment_line(text: str) -> bool:
    """True when the payslip shows a previous-employment YTD carry-forward."""
    return _PREVIOUS_EMPLOYMENT_RE.search(text) is not None


_TAX_CODE_RE = re.compile(
    r"^[SC]?\d{1,4}[LMNPTY](?:\s?(?:W1|M1|X))?$"
    r"|^[SC]?(?:BR|D0|D1|0T|NT)(?:\s?(?:W1|M1|X))?$"
    r"|^[SC]?K\d{1,4}(?:\s?(?:W1|M1|X))?$",
    re.IGNORECASE,
)


# Every dotted path _ModelExtract can legitimately report a value or a
# confidence score for. Used to normalise unreadable_fields/confidence
# keys to a consistent dotted form - see _normalize_field_paths().
_KNOWN_FIELD_PATHS = frozenset(
    {
        "employer_name",
        "period.pay_date",
        "period.period_number",
        "period.frequency",
        "tax_code.value",
        "pay.hourly_rate",
        "pay.hours",
        "pay.gross_this_period",
        "pay.gross_ytd",
        "deductions.income_tax",
        "deductions.income_tax_ytd",
        "deductions.national_insurance",
        "deductions.national_insurance_ytd",
        "deductions.ni_category",
        "deductions.pension_employee",
        "deductions.pension_employer",
        "deductions.pension_percent",
        "deductions.student_loan",
        "deductions.student_loan_plan",
        "net_pay",
    }
)


def _normalize_dotted_path(path: str, warnings_out: list[str]) -> Optional[str]:
    """Resolve `path` to a full dotted path in _KNOWN_FIELD_PATHS. A path
    already dotted and known is returned as-is; a bare leaf name (e.g.
    "student_loan") resolves if exactly one known field ends with it.
    Anything that resolves to zero or more-than-one field is dropped
    (with a warning) rather than guessed."""
    if path in _KNOWN_FIELD_PATHS:
        return path
    leaf = path.rsplit(".", 1)[-1]
    matches = [known for known in _KNOWN_FIELD_PATHS if known.rsplit(".", 1)[-1] == leaf]
    if len(matches) == 1:
        return matches[0]
    warnings_out.append(f"could not resolve field path {path!r} to a known field - dropped")
    return None


def _normalize_path_list(paths: list[str], warnings_out: list[str]) -> list[str]:
    """Resolve every entry in `paths` via _normalize_dotted_path,
    dropping anything unresolvable."""
    normalized = []
    for path in paths:
        resolved = _normalize_dotted_path(path, warnings_out)
        if resolved is not None:
            normalized.append(resolved)
    return normalized


def _normalize_field_paths(model_extract: "_ModelExtract", warnings_out: list[str]) -> None:
    """
    Normalises model_extract.unreadable_fields, .ambiguous_fields, and
    the keys of model_extract.confidence to full dotted paths, in place.

    The extraction prompt asks for dotted paths, but a live run returned
    a mix of "period.frequency" (dotted) and "student_loan" (bare) in the
    same response. The findings layer matches a rule's
    Finding.source_fields (always dotted, e.g. "deductions.student_loan")
    against unreadable_fields - if the formats differ, that match
    silently fails and a rule runs on a field we could not actually read.
    Not relying on the prompt to get this right is the point.
    """
    model_extract.unreadable_fields = _normalize_path_list(
        model_extract.unreadable_fields, warnings_out
    )
    model_extract.ambiguous_fields = _normalize_path_list(
        model_extract.ambiguous_fields, warnings_out
    )

    normalized_confidence = {}
    for path, score in model_extract.confidence.items():
        resolved = _normalize_dotted_path(path, warnings_out)
        if resolved is not None:
            normalized_confidence[resolved] = score
    model_extract.confidence = normalized_confidence


def _cap_ambiguous_field_confidence(model_extract: "_ModelExtract") -> None:
    """
    Cap confidence only for fields the model explicitly named in
    ambiguous_fields - never by scanning warning prose for keywords.

    An earlier version inferred ambiguity from warning text (matching a
    field's dotted path or common printed label against the warning
    string). It over-fired badly: most warnings are informational, not
    expressions of doubt. On a live run, "Tax code 0T M1 is an
    emergency/non-cumulative code" - the single most useful insight this
    product surfaces - got tax_code.value deleted, and one payslip lost
    seven fields including gross, net and both YTD figures to warnings
    that were just explaining a choice, not flagging uncertainty about
    it. Asking the model for structure (ambiguous_fields) instead of
    inferring structure from prose is the fix, not a better keyword list.

    Caps at just under the threshold rather than zeroing outright, so the
    normal "confidence < threshold" check below is what actually moves it
    into unreadable_fields - one rule, not two.
    """
    for dotted_path in model_extract.ambiguous_fields:
        current = model_extract.confidence.get(dotted_path, _CONFIDENCE_THRESHOLD)
        model_extract.confidence[dotted_path] = min(current, _CONFIDENCE_THRESHOLD - 0.01)


def _null_dotted(data: dict, dotted_path: str) -> None:
    """Set data['a']['b'] = None given dotted_path 'a.b' (or data['a'] =
    None given just 'a'). Used to null out unreadable fields by the same
    dotted-path keys PayslipExtract.confidence and .unreadable_fields
    already use."""
    parts = dotted_path.split(".")
    target = data
    for part in parts[:-1]:
        target = target.get(part, {})
        if not isinstance(target, dict):
            return
    if isinstance(target, dict) and parts[-1] in target:
        target[parts[-1]] = None


def _reconciles(extract_dict: dict, unreadable: set[str]) -> Optional[bool]:
    """
    gross - all deductions == net, to the penny. Computed here, never
    asked of the model.

    A deduction field that is simply None (the model never flagged it)
    is treated as a genuine zero - real payslips print explicit "0.00"
    lines for deductions that don't apply, so "not present" and "present
    as zero" are meant to be the same thing here. A field the model or
    the checks above flagged as unreadable is different: that means "we
    don't trust this figure," not "there is no such deduction," so it
    aborts the check entirely.

    Returns None, not False, when there isn't enough trustworthy data to
    check at all. False is reserved for "we checked, and it's wrong."
    """
    pay = extract_dict["pay"]
    deductions = extract_dict["deductions"]
    gross = pay.get("gross_this_period")
    net = extract_dict.get("net_pay")

    if gross is None or net is None:
        return None

    component_fields = (
        "income_tax",
        "national_insurance",
        "pension_employee",
        "student_loan",
    )
    total = Decimal("0")
    for field_name in component_fields:
        dotted_path = f"deductions.{field_name}"
        if dotted_path in unreadable:
            return None
        value = deductions.get(field_name)
        total += value if value is not None else Decimal("0")

    for item in deductions.get("other") or []:
        total += item["amount"]

    return (gross - total) == net


def extract_payslip(pdf_bytes: bytes, filename: Optional[str] = None) -> PayslipExtract:
    """
    Orchestrates the full pipeline: read -> redact -> filter -> safety
    gate -> model call -> validate -> compute what the model is never
    trusted to compute itself.

    `filename` is metadata only, supplied by the caller - it is never
    read from disk here and never sent to the model (filenames can
    contain names). It only ends up on the returned Source, for callers
    that want it on the record (golden-file tests, mainly).

    Raises NotAPayslip / UnreadableDocument rather than returning
    half-filled data - a missing field is fine, a wrong field is not.
    """
    text, page_count = _read_pdf(pdf_bytes)
    redacted_text, redaction_map = redact(text)
    filtered_text = financial_lines_only(redacted_text)
    assert_safe_to_send(filtered_text)

    model_extract = _call_model(filtered_text)
    if not model_extract.is_payslip:
        raise NotAPayslip("model reports this document is not a payslip")

    # See _normalize_field_paths(): live output has mixed dotted and bare
    # field names, which silently breaks the findings layer's confidence
    # gate. Fix that before anything below reads unreadable_fields or
    # confidence.
    path_warnings: list[str] = []
    _normalize_field_paths(model_extract, path_warnings)

    # A field the model explicitly named in ambiguous_fields should not
    # also sail through on a high confidence score.
    _cap_ambiguous_field_confidence(model_extract)

    # unreadable_fields the model already flagged, plus anything it was
    # under-confident about even without flagging it.
    unreadable: set[str] = set(model_extract.unreadable_fields)
    for dotted_path, score in model_extract.confidence.items():
        if score < _CONFIDENCE_THRESHOLD:
            unreadable.add(dotted_path)

    tax_code_value = model_extract.tax_code.value
    if tax_code_value is not None and not _TAX_CODE_RE.match(tax_code_value.strip()):
        unreadable.add("tax_code.value")

    pay, deductions = model_extract.pay, model_extract.deductions
    if (
        pay.gross_this_period is not None
        and pay.gross_ytd is not None
        and pay.gross_ytd < pay.gross_this_period
    ):
        unreadable.add("pay.gross_ytd")
    if (
        deductions.income_tax is not None
        and deductions.income_tax_ytd is not None
        and deductions.income_tax_ytd < deductions.income_tax
    ):
        unreadable.add("deductions.income_tax_ytd")
    if (
        deductions.national_insurance is not None
        and deductions.national_insurance_ytd is not None
        and deductions.national_insurance_ytd < deductions.national_insurance
    ):
        unreadable.add("deductions.national_insurance_ytd")

    # period_number is arithmetic from the pay date, not something to
    # read off the page (see derive_period_number) - it drives the
    # cumulative tax calculation, so it is always derived when possible,
    # and a model-reported value that disagrees is overridden, not
    # merged, with a warning naming both.
    #
    # Only attempt this with a frequency we actually trust: not None, and
    # not already flagged unreadable (e.g. by a low confidence score).
    # frequency=None with period_number=9 at confidence 1.0 happened on a
    # live run - something assumed monthly and reported the guess as
    # certain. A confidence of 1.0 must only ever come from a value
    # genuinely derived from a known frequency and a known pay date.
    period_number = model_extract.period.period_number
    confidence = dict(model_extract.confidence)
    frequency = model_extract.period.frequency
    pay_date = model_extract.period.pay_date

    # Same reasoning as the frequency read below, and the same guard:
    # only when the model returned nothing. This is what makes the
    # result stable run to run - pay_date gates period_number, which
    # gates the entire calculation, so a model that reads it on one run
    # and misses it on the next makes "We could not complete every
    # calculation" appear intermittently on an unchanged payslip.
    if pay_date is None:
        pay_date = read_pay_date_from_label(filtered_text)
        if pay_date is not None:
            unreadable.discard("period.pay_date")
            path_warnings.append(
                f"period.pay_date: read from its printed label ({pay_date}) - "
                f"the model did not return one."
            )

    # Only when the model returned NOTHING for frequency - not when it
    # returned a value it flagged unreadable, which is a different
    # situation (it saw something and doubted it, rather than finding
    # nothing to read). See infer_frequency_from_label().
    if frequency is None:
        inferred_frequency = infer_frequency_from_label(filtered_text)
        if inferred_frequency is not None:
            frequency = inferred_frequency
            unreadable.discard("period.frequency")
            path_warnings.append(
                f"period.frequency: read from a printed period label "
                f"({inferred_frequency}) - the payslip does not state the "
                f"frequency as a word."
            )

    frequency_known = frequency is not None and "period.frequency" not in unreadable
    derived_period_number = (
        derive_period_number(pay_date, frequency)
        if frequency_known
        else None
    )
    if derived_period_number is not None:
        # Guard: pay date present -> derive as always. This branch is
        # unchanged and takes priority regardless of anything the model
        # separately reported - see the fallback branch below for why a
        # disagreement here doesn't get a different resolution.
        if period_number is not None and period_number != derived_period_number:
            path_warnings.append(
                "period.period_number: model reported "
                f"{period_number}, derived {derived_period_number} from "
                "the pay date - using the derived value"
            )
        period_number = derived_period_number
        confidence["period.period_number"] = 1.0
        unreadable.discard("period.period_number")

    elif (
        frequency_known
        and pay_date is None
        and period_number is not None
        and "period.period_number" not in unreadable
        and _period_number_plausible(period_number, frequency)
    ):
        # No pay date to derive from, but the payslip prints an explicit
        # period label (e.g. "Month 9") that the model read confidently,
        # and it's a plausible value for the frequency we've separately
        # confirmed. This is not the failure the strict branch above
        # guards against: that was the model inventing a number with no
        # signal behind it. Reading a printed label is extraction - the
        # same operation already trusted for tax code and gross pay -
        # not the model guessing. Left as read, not promoted to 1.0
        # confidence: it still carries whatever uncertainty the model
        # itself reported about having read it correctly, unlike a
        # derived value which is mathematically certain given accurate
        # inputs.
        path_warnings.append(
            f"period.period_number: read directly from a printed period "
            f"label ({period_number}) - no pay date was available to "
            f"derive it independently."
        )

    else:
        # No trustworthy frequency and/or pay date to derive from, and
        # no safely-acceptable printed period label either (out of
        # range for the stated frequency, frequency itself unconfirmed,
        # or the model didn't report one confidently) - never fall back
        # to a model-guessed period_number here, even if the model
        # itself reported it confidently. Assuming a frequency and then
        # reporting the result as certain is exactly the failure this
        # whole function exists to prevent.
        period_number = None
        confidence.pop("period.period_number", None)
        unreadable.add("period.period_number")

    tax_year = (
        _tax_year_for(pay_date)
        if pay_date is not None
        else None
    )

    extract_dict = model_extract.model_dump(
        exclude={"is_payslip", "unreadable_fields", "confidence"}
    )
    extract_dict["confidence"] = confidence
    extract_dict["period"]["period_number"] = period_number
    extract_dict["period"]["frequency"] = frequency
    # Must be the resolved value, not the model's: deriving period_number
    # from a label-read pay date while still reporting pay_date as null
    # would leave the extract self-contradictory.
    extract_dict["period"]["pay_date"] = pay_date
    extract_dict["period"]["tax_year"] = tax_year
    # employer_name never reaches the model - the allowlist drops that
    # line outright (no currency, date or known label on it) - so it's
    # captured separately during redact() and applied here instead.
    # From the redacted text, not the filtered payload: a bare "Previous
    # Employment" header carries no currency amount and the allowlist would
    # drop it, but the header alone is still evidence that this payslip's
    # YTD column does not cover the whole tax year.
    extract_dict["previous_employment_ytd_present"] = has_previous_employment_line(
        redacted_text
    )
    extract_dict["employer_name"] = redaction_map.employer_name
    if redaction_map.employer_name is None:
        path_warnings.append("employer name was not confidently identified")
    extract_dict["source"] = Source(
        filename=filename, pages=page_count, scanned_at=datetime.now(timezone.utc)
    )
    extract_dict["warnings"] = [*model_extract.warnings, *path_warnings]

    # reconciles is computed from the pre-nulling values (it needs
    # `unreadable` to tell a genuine zero apart from a suspect field -
    # see _reconciles), then everything unreadable gets nulled out
    # afterwards so it can never reach the frontend regardless.
    extract_dict["reconciles"] = _reconciles(extract_dict, unreadable)
    for dotted_path in unreadable:
        _null_dotted(extract_dict, dotted_path)
    extract_dict["unreadable_fields"] = sorted(unreadable)

    try:
        return PayslipExtract(**extract_dict)
    except ValidationError as exc:
        raise NotAPayslip(f"extract failed contract validation: {exc}") from exc
