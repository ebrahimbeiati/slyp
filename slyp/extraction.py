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
_SORT_CODE_RE = re.compile(r"\b\d{2}[-\s/]\d{2}[-\s/]\d{2}\b")

# Account number: 8 digits, each optionally separated from the next by
# one of the same characters (excluding "." for the same reason as sort
# code, above). Deliberately not label-anchored - real payslips don't
# always print an "Account Number:" label next to it. That also makes it
# the noisiest pattern here (an 8-digit reference number would also
# match); assert_safe_to_send and the allowlist are the backstops for
# what this over-redacts or misses, not this regex alone.
_ACCOUNT_NUMBER_RE = re.compile(r"\b\d(?:[-\s/]?\d){7}\b")

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
_NAME_LABEL_RE = re.compile(r"(?im)^(Employee Name|Name)\s*:?\s*(.+)$")
_ADDRESS_LABEL_RE = re.compile(r"(?im)^(Address|Home Address)\s*:?\s*(.+)$")

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
    text: str, pattern: re.Pattern[str], token: str, redaction_map: RedactionMap
) -> str:
    """Replace every whole match of `pattern` with `token`."""

    def _sub(match: re.Match[str]) -> str:
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
    [BANK], [EMAIL], [PHONE]) rather than deleting it - layout matters,
    and a deleted span would just shift everything after it.

    Must run before financial_lines_only(). See the module docstring for
    why: a line can carry both PII and a currency amount together.
    """
    redaction_map = RedactionMap()
    redacted = text

    # Order matters here too: NI number and postcode are the most
    # specific patterns (least likely to over-match), so they run before
    # the looser 8-digit account number check gets a chance at the same
    # digits.
    redacted = _redact_pattern(redacted, _NI_NUMBER_RE, "[NI]", redaction_map)
    redacted = _redact_pattern(redacted, _POSTCODE_RE, "[ADDRESS]", redaction_map)
    redacted = _redact_pattern(redacted, _SORT_CODE_RE, "[BANK]", redaction_map)
    redacted = _redact_pattern(redacted, _ACCOUNT_NUMBER_RE, "[BANK]", redaction_map)
    redacted = _redact_pattern(redacted, _EMAIL_RE, "[EMAIL]", redaction_map)
    redacted = _redact_pattern(redacted, _PHONE_RE, "[PHONE]", redaction_map)
    redacted = _redact_labelled(redacted, _EMPLOYEE_NO_LABEL_RE, "[EMPLOYEE_NO]", redaction_map)
    redacted = _redact_labelled(redacted, _NAME_LABEL_RE, "[NAME]", redaction_map)
    redacted = _redact_labelled(redacted, _ADDRESS_LABEL_RE, "[ADDRESS]", redaction_map)

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
_DATE_RE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?[-\s](?:{_MONTH_NAMES})[a-z]*[-\s]\d{{2,4}}\b"
    rf"|\b\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}\b",
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
    r"pay period|pay date|tax period|tax month|tax week|period number|"
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


def financial_lines_only(text: str) -> str:
    """
    Allowlist filter: keep a line only if it contains a currency amount,
    a percentage, a date, a tax-code pattern, or a known payslip label.
    Everything else is dropped unseen.

    This is the primary privacy control, not a secondary one. It catches
    whatever the redaction regexes above missed - most importantly an
    unlabelled name or address line, which has no shape a PII regex can
    anchor to but also has no financial content, so it never survives
    this filter either way.

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

_PII_RECHECK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("NI number", _NI_NUMBER_RE),
    ("postcode", _POSTCODE_RE),
    ("sort code", _SORT_CODE_RE),
    ("account number", _ACCOUNT_NUMBER_RE),
    ("email", _EMAIL_RE),
    ("phone", _PHONE_RE),
)

# A run of 6 or more digits, tolerating the same separators as the
# structured-number patterns above. Used only as the SECOND, independent
# check in assert_safe_to_send() - see there for why. Applied to text that
# has already had every recognised-safe numeric shape (currency, percent,
# date, tax code) masked out, so a legitimate payslip figure never reaches
# it: by that point in the pipeline, any digit run this long left over
# isn't a gross figure or a YTD total (both always have a two-decimal-
# place currency shape in this codebase), it's something unaccounted for.
_UNEXPLAINED_DIGIT_RUN_RE = re.compile(r"(?:\d[\s./-]*){6,}")


def _mask_known_safe_numbers(text: str) -> str:
    """Strip every span that legitimately explains a run of digits on a
    payslip line, leaving only what neither the allowlist nor a normal
    payslip figure accounts for."""
    masked = _CURRENCY_RE.sub(" ", text)
    masked = _PERCENT_RE.sub(" ", masked)
    masked = _DATE_RE.sub(" ", masked)
    masked = _TAX_CODE_LINE_RE.sub(" ", masked)
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
       date, tax code) and refuses if 6 or more digits remain anywhere in
       what's left. This doesn't know what an NI number, sort code or
       account number looks like, so it can't share check 1's blind spot
       for a shape neither regex set recognises yet - it catches by the
       ABSENCE of an explanation for a run of digits, not by recognising
       a specific kind of personal data. "Two labels on one control" is
       exactly what this function used to be with only check 1.

    Deliberately does not include the matched text in the exception
    message - the point of this function is to stop PII leaving the
    process, so it must not leak it into a log line instead.
    """
    for label, pattern in _PII_RECHECK_PATTERNS:
        if pattern.search(payload):
            raise RedactionFailure(f"payload still matches a PII pattern: {label}")

    if _UNEXPLAINED_DIGIT_RUN_RE.search(_mask_known_safe_numbers(payload)):
        raise RedactionFailure(
            "payload has an unexplained run of digits with no financial shape"
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

    try:
        response = _create()
    except openai.BadRequestError as exc:
        # Some reasoning-capable models reject a tool call unless
        # reasoning_effort is explicitly turned off for it (confirmed
        # live against gpt-5.6-terra: "Function tools with
        # reasoning_effort are not supported ... set reasoning_effort to
        # 'none'"). Retry once with it added rather than sending it
        # unconditionally - a model that doesn't recognise the parameter
        # at all would otherwise break on every call instead of none.
        if "reasoning_effort" in str(exc):
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


# Best-effort validation of the tax code shapes types.TaxCodeKind
# recognises. A code failing this doesn't raise - it just means
# tax_code.value goes into unreadable_fields like any other suspect
# field, per "a missing field is fine, a wrong field is not."
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
    frequency_known = (
        model_extract.period.frequency is not None
        and "period.frequency" not in unreadable
    )
    derived_period_number = (
        derive_period_number(model_extract.period.pay_date, model_extract.period.frequency)
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
        and model_extract.period.pay_date is None
        and period_number is not None
        and "period.period_number" not in unreadable
        and _period_number_plausible(period_number, model_extract.period.frequency)
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
        _tax_year_for(model_extract.period.pay_date)
        if model_extract.period.pay_date is not None
        else None
    )

    extract_dict = model_extract.model_dump(
        exclude={"is_payslip", "unreadable_fields", "confidence"}
    )
    extract_dict["confidence"] = confidence
    extract_dict["period"]["period_number"] = period_number
    extract_dict["period"]["tax_year"] = tax_year
    # employer_name never reaches the model - the allowlist drops that
    # line outright (no currency, date or known label on it) - so it's
    # captured separately during redact() and applied here instead.
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
