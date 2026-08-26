from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from slyp.extraction import (
    _DATE_RE,
    _mask_known_safe_numbers,
    _SORT_CODE_RE,
    has_previous_employment_line,
    RedactionFailure,
    RedactionMap,
    _cap_ambiguous_field_confidence,
    _CONFIDENCE_THRESHOLD,
    _find_employer_name,
    _ModelExtract,
    _normalize_field_paths,
    _reconciles,
    _tax_year_for,
    assert_safe_to_send,
    derive_period_number,
    extract_payslip,
    extract_text,
    financial_lines_only,
    infer_frequency_from_label,
    redact,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _make_pdf_bytes(lines: list[str]) -> bytes:
    """
    Hand-rolled minimal single-page PDF containing `lines` as a text
    layer. No PDF-authoring library is a project dependency, so this
    builds the raw PDF structure directly - just enough for pdfplumber to
    read a text layer back out. Test-only; never used outside this file.
    """
    content_ops = ["BT", "/F1 12 Tf", "20 780 Td"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_ops.append(f"({escaped}) Tj")
        content_ops.append("0 -14 Td")
    content_ops.append("ET")
    content = " ".join(content_ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 600 800] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (f"<< /Length {len(content)} >>\nstream\n".encode("latin-1"))
        + content
        + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    xref_offset = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode("latin-1") + b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("latin-1")
    return bytes(out)


def _empty_pdf_bytes() -> bytes:
    return _make_pdf_bytes([])


# The real (personal values already replaced) sample from tools/inspect_payslip.py
SAMPLE_TEXT = """\
Easy Gourmet Ltd
Ref: 948 / E112369
[NAME] Payments
Pay Period Mar-2026 Description Hours Rate Amount
Pay Date 31-Mar-2026 Rate 1 37.60 13.85 520.76
Pay Type Monthly Hourly Holiday Rate 317.60 1.67 62.79
Payment Method Bank Transfer Total Hourly Pay 583.55
Total Payments 583.55
Works Number 602
Department Work Away Manual worker Deductions
Tax Code 1257L Income Tax 0.00
NI Number AB 12 34 56 C National Insurance 0.00
NI Table Letter A Total Deductions 0.00
Year to Date
Taxable Gross Pay 854.07
Income Tax 0.00
Employee NIC 0.00
Employer NIC 24.98
Week 16th March (20 hours) & Week 23rd March (17.60 hours)
Net Pay 583.55
"""

# SAMPLE_TEXT prints "Pay Type Monthly", so infer_frequency_from_label()
# reads a frequency straight off it - correctly, it's printed there. The
# tests below that need frequency to be genuinely UNKNOWABLE have to use
# a payslip that never states it, or they'd be asserting against an
# inference that legitimately succeeded rather than against the
# never-guess property they exist to protect.
SAMPLE_TEXT_NO_FREQUENCY = SAMPLE_TEXT.replace("Pay Type Monthly", "Pay Type")

# Same again for the pay date: SAMPLE_TEXT prints "Pay Date 31-Mar-2026",
# so read_pay_date_from_label() recovers it even when the model returns
# none. Tests for the printed-period-label fallback need a payslip where
# the pay date is genuinely unavailable, since that fallback exists
# precisely for when there's nothing to derive from.
SAMPLE_TEXT_NO_PAY_DATE = SAMPLE_TEXT.replace("Pay Date 31-Mar-2026 ", "")


# --------------------------------------------------------------------------
# extract_text
# --------------------------------------------------------------------------


def test_extract_text_reads_the_text_layer():
    pdf_bytes = _make_pdf_bytes(["Gross Pay 2500.00", "Net Pay 1900.00"])
    text = extract_text(pdf_bytes)
    assert "Gross Pay 2500.00" in text
    assert "Net Pay 1900.00" in text


def test_extract_text_raises_on_no_text_layer():
    from slyp.extraction import UnreadableDocument

    with pytest.raises(UnreadableDocument):
        extract_text(_empty_pdf_bytes())


# --------------------------------------------------------------------------
# redact() - canary values
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "canary",
    [
        "AB 12 34 56 C",  # spaced NI number - the real-world case
        "AB123456C",  # compact NI number
        "AB.12.34.56.C",  # periods (F6 - was a full bypass)
        "ry449943d",  # lowercase, no separators
        "ZZ99 9ZZ",  # postcode
        "12-34-56",  # sort code, dashed
        "12 34 56",  # sort code, spaced
        "12/34/56",  # sort code, slashed (F6 - was a full bypass)
        "12-34/56",  # sort code, mixed separators
    ],
)
def test_canary_values_do_not_survive_redaction(canary):
    text = f"Some line containing {canary} in the middle of it"
    redacted, redaction_map = redact(text)
    assert canary not in redacted
    assert any(canary in values for values in redaction_map.replacements.values())


def test_ni_number_split_across_a_line_break_is_redacted():
    text = "NI Number RY 44 99\n43 D National Insurance 0.00"
    redacted, redaction_map = redact(text)
    assert "RY 44 99\n43 D" not in redacted
    assert "[NI]" in redacted


def test_canary_values_do_not_survive_the_full_outbound_payload():
    text = (
        "NI Number AB 12 34 56 C National Insurance 0.00\n"
        "Address line SW1A 1AA more text\n"
        "Sort code 12-34-56 Account details\n"
    )
    redacted, _ = redact(text)
    payload = financial_lines_only(redacted)

    for canary in ["AB 12 34 56 C", "AB123456C", "SW1A 1AA", "12-34-56"]:
        assert canary not in payload

    # Proves the payload really is clean, not just "happens to pass these
    # particular string checks" - assert_safe_to_send re-scans with the
    # same patterns redact() uses and must not raise.
    assert_safe_to_send(payload)


def test_email_and_phone_are_redacted():
    text = "Contact payroll@example.com or call 07911 123456 for queries"
    redacted, redaction_map = redact(text)
    assert "payroll@example.com" not in redacted
    assert "07911 123456" not in redacted
    assert "[EMAIL]" in redacted
    assert "[PHONE]" in redacted


def test_labelled_name_and_address_are_redacted():
    text = "Employee Name: Jane Doe\nAddress: 12 High Street"
    redacted, redaction_map = redact(text)
    assert "Jane Doe" not in redacted
    assert "12 High Street" not in redacted
    assert "[NAME]" in redacted
    assert "[ADDRESS]" in redacted


def test_titled_name_sharing_a_line_with_a_date_is_redacted():
    """
    The row that broke the "allowlist catches unlabelled names" claim, from
    a real payslip: name, pay date and NI number collapsed onto one line.
    The NI number was already redacted; the date then kept the whole line
    through the allowlist, carrying the name to the model with it.
    """
    line = "1195 Mr. K SAMPLE 13/02/2026 AB123456C"
    payload = financial_lines_only(redact(line)[0])

    assert "SAMPLE" not in payload
    assert "[NAME]" in payload
    # the line still survives, and the pay date on it is untouched -
    # period_number is derived from that date
    assert "13/02/2026" in payload


def test_titled_name_does_not_swallow_the_payslip_label_beside_it():
    """Over-redaction here costs a field, so the name match stops at the
    first payslip word rather than running to the end of the line."""
    redacted, _ = redact("Mr J Smith PAYE Tax 0.00")

    assert "Smith" not in redacted
    assert redacted == "[NAME] PAYE Tax 0.00"


@pytest.mark.parametrize(
    "line",
    [
        "Employer NIC 24.98",
        "Total Gross Pay 79.64",
        "Tax Code: 1257L W1 Dept: Tax Period: 45 Method: BACS",
        "Miss Pay 10.00",  # title followed immediately by a stop word
    ],
)
def test_titled_name_pattern_leaves_financial_lines_alone(line):
    assert redact(line)[0] == line


def test_labelled_employee_number_is_redacted():
    redacted, redaction_map = redact("Works Number 602")
    assert "602" not in redacted
    assert "[EMPLOYEE_NO]" in redacted


def test_multi_line_address_is_dropped_by_the_allowlist():
    # A multi-line address has no labelled anchor on every line, so
    # redact() only catches the postcode - it's financial_lines_only()
    # that drops the unlabelled street/town lines, since they carry no
    # currency, date, tax-code or known-label content either.
    text = "123 Fake Street\nFaketown\nSW1A 1AA"
    redacted, _ = redact(text)
    payload = financial_lines_only(redacted)
    assert "123 Fake Street" not in payload
    assert "Faketown" not in payload
    assert "SW1A 1AA" not in payload
    assert_safe_to_send(payload)


# --------------------------------------------------------------------------
# redact() - the date / account-number collision
#
# _ACCOUNT_NUMBER_RE (broadened for F6 to tolerate "/" as a separator)
# matches a DD/MM/YYYY date exactly: 8 digits, slash-separated. A live
# run showed "Pay Date 15/12/2025" silently becoming "Pay Date [BANK]"
# before the model ever saw a date - not an allowlist or model-vocabulary
# problem, a genuine redaction bug. Every case below also carries a real
# account number on the same line, to prove the fix distinguishes the two
# rather than just accepting anything shaped like 8 digits with
# separators.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pay_date_text",
    [
        "15/12/2025",  # DD/MM/YYYY
        "15-12-2025",  # DD-MM-YYYY
        "5/3/25",  # D/M/YY - too few digits to hit either bank pattern at all
        "2025-12-15",  # YYYY-MM-DD
    ],
)
def test_date_survives_redaction_with_an_adjacent_account_number(pay_date_text):
    text = f"Pay Date {pay_date_text} Account 12345678"
    redacted, _ = redact(text)
    assert pay_date_text in redacted, f"date {pay_date_text!r} was redacted: {redacted!r}"
    assert "12345678" not in redacted
    assert "[BANK]" in redacted


@pytest.mark.parametrize(
    "account_text",
    [
        "12345678",  # no separators
        "1234-5678",  # dash
        "1234 5678",  # space
        "1234/5678",  # slash
        "12-34-56-78",  # multiple dashes
    ],
)
def test_account_number_still_redacted_in_every_separator_form(account_text):
    text = f"Pay Date 15/12/2025 Account {account_text}"
    redacted, _ = redact(text)
    assert account_text not in redacted
    assert "15/12/2025" in redacted
    assert "[BANK]" in redacted


@pytest.mark.parametrize(
    "pay_date_text",
    [
        "15/12/2025",  # DD/MM/YYYY
        "15-12-2025",  # DD-MM-YYYY
        "2025-12-15",  # YYYY-MM-DD (ISO) - regressed the gate, not just redact()
        "2025/12/15",  # YYYY/MM/DD
    ],
)
def test_date_survives_the_full_pipeline_including_the_gate(pay_date_text):
    # redact() surviving a date isn't enough on its own - _DATE_RE is a
    # second, separate pattern from the account-number exemption above,
    # used both by the allowlist and by assert_safe_to_send's independent
    # digit-run check. An ISO date passed the account-number exemption
    # but _DATE_RE didn't recognise year-first dates yet, so the date's
    # leftover digits looked "unexplained" to the gate and got refused -
    # a live 422 that only surfaced once a real ISO-dated payslip was
    # run, because no existing test called assert_safe_to_send() on a
    # payload containing a surviving date. This test goes through the
    # whole pipeline for exactly that reason.
    text = (
        f"Pay Date {pay_date_text} Tax Code 1257L "
        f"Gross 2500.00 Net 2000.00"
    )
    redacted, _ = redact(text)
    filtered = financial_lines_only(redacted)
    assert pay_date_text in filtered
    assert_safe_to_send(filtered)  # must not raise


def test_sort_code_with_slashes_bypass_not_reopened_by_the_date_exemption():
    """F6 regression guard: a 6-digit sort-code-with-slashes bypass must
    never be exempted just because it superficially resembles a date-
    shaped sequence - it structurally can't have a 4-digit year group,
    but this pins the behaviour down explicitly rather than relying on
    that reasoning holding forever."""
    redacted, _ = redact("Sort Code 12/34/56 Account 12345678")
    assert "12/34/56" not in redacted
    assert redacted.count("[BANK]") == 2


@pytest.mark.parametrize(
    "implausible_text",
    [
        "45/67/2025",  # month 67 - not a real date, must still redact
        "99/99/2025",  # neither day nor month valid
    ],
)
def test_implausible_date_shaped_sequence_still_redacted_as_account_number(implausible_text):
    redacted, _ = redact(f"Reference {implausible_text}")
    assert implausible_text not in redacted
    assert "[BANK]" in redacted


# --------------------------------------------------------------------------
# financial_lines_only() - the allowlist
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "[NAME] Payments",
        "Ref: 948 / E112369",
        "Works Number 602",
        "Easy Gourmet Ltd",
    ],
)
def test_allowlist_drops_lines_with_no_financial_content(line):
    kept = financial_lines_only(line)
    assert kept == ""


@pytest.mark.parametrize(
    "line",
    [
        "Tax Code 1257L Income Tax 0.00",
        "Gross Pay 2500.00",
        "Pay Date 31-Mar-2026 Rate 1 37.60 13.85 520.76",
        "National Insurance 0.00",
    ],
)
def test_allowlist_keeps_lines_with_financial_content(line):
    kept = financial_lines_only(line)
    assert kept == line


def test_allowlist_keeps_a_payment_period_line_with_no_figure_on_it():
    """
    "Payment Period    Weekly" is the only statement of frequency on a
    real weekly payslip, and it carries no currency amount, date,
    percentage or tax code - the label alone has to keep it. It didn't:
    the vocabulary had "pay period", which "Payment Period" does not
    contain, so the line was dropped and frequency came back null.
    """
    assert financial_lines_only("Payment Period Weekly") == "Payment Period Weekly"
    assert financial_lines_only("Pay Period Monthly") == "Pay Period Monthly"


def test_frequency_survives_the_allowlist_on_the_real_weekly_payslip():
    """
    End-to-end on the shape that produced "We could not complete every
    calculation": frequency has to survive redact() AND the allowlist to
    be readable, because infer_frequency_from_label() runs on the
    filtered payload, not the raw text.
    """
    text = "\n".join(
        [
            "1195 Mr. K SAMPLE 13/02/2026 AB123456C",
            "Total Gross Pay 79.64 Total Gross Pay TD 79.64",
            "Payment Period Weekly",
            "Tax Code: 1257L W1 Dept: Tax Period: 45 Method: BACS",
        ]
    )
    payload = financial_lines_only(redact(text)[0])

    assert infer_frequency_from_label(payload) == "weekly"
    # and with the frequency known, the pay date on the identity row is
    # all the period number needs
    assert derive_period_number(date(2026, 2, 13), "weekly") == 45


def test_redaction_runs_before_filtering_on_the_real_sample():
    """
    The key ordering case: a line with BOTH an NI number and a currency
    amount. The allowlist keeps the line (it has an amount) - the only
    thing standing between the NI number and the model is redact()
    having already run first.
    """
    redacted, _ = redact(SAMPLE_TEXT)
    payload = financial_lines_only(redacted)

    assert "AB 12 34 56 C" not in payload
    assert "[NI]" in payload
    # the line survives (it has a currency amount) - just without the NI number
    assert "National Insurance 0.00" in payload

    # and the unlabelled name/ref/works-number lines are gone, per finding 3
    assert "[NAME] Payments" not in payload
    assert "Ref: 948" not in payload
    assert "Works Number" not in payload


# --------------------------------------------------------------------------
# assert_safe_to_send
# --------------------------------------------------------------------------


def test_assert_safe_to_send_raises_on_unredacted_pii():
    with pytest.raises(RedactionFailure):
        assert_safe_to_send("NI Number AB 12 34 56 C National Insurance 0.00")


def test_assert_safe_to_send_raises_on_an_unredacted_titled_name():
    """A name is the one PII class the gate's second (digit-run) check
    cannot see at all, so the re-scan has to carry it."""
    with pytest.raises(RedactionFailure):
        assert_safe_to_send("1195 Mr. K SAMPLE 13/02/2026")


def test_assert_safe_to_send_does_not_raise_on_clean_text():
    assert_safe_to_send("Gross Pay 2500.00\nNet Pay 1900.00")


def test_assert_safe_to_send_does_not_leak_the_match_in_its_message():
    try:
        assert_safe_to_send("contact me on payroll@example.com")
    except RedactionFailure as exc:
        assert "payroll@example.com" not in str(exc)
    else:
        pytest.fail("expected RedactionFailure")


def test_gate_catches_a_shape_none_of_the_named_pii_patterns_recognise():
    """
    The independence check for the gate's second layer (item 35): a bare
    digit run that doesn't match ANY of the specific PII shapes redact()
    knows about (not an NI number, not a sort code, not an account
    number, not a phone number) still trips the gate, because it has no
    financial explanation (no currency/percent/date/tax-code shape). This
    is the property that makes the gate more than "the same regex, run
    twice" - see slyp.extraction._PII_RECHECK_PATTERNS.
    """
    from slyp.extraction import _PII_RECHECK_PATTERNS

    payload = "Some Internal Reference 123456789 National Insurance 0.00"

    assert not any(pattern.search(payload) for _label, pattern, _skip_if in _PII_RECHECK_PATTERNS)

    with pytest.raises(RedactionFailure):
        assert_safe_to_send(payload)


def test_gate_does_not_false_positive_on_clean_multi_field_text():
    payload = (
        "Tax Code 1257L Income Tax 0.00\n"
        "Pay Date 31-Mar-2026 Rate 1 37.60 13.85 520.76\n"
        "National Insurance 0.00\n"
        "Taxable Gross Pay 854.07\n"
    )
    assert_safe_to_send(payload)


# --------------------------------------------------------------------------
# The gate's second check: whitespace is ambiguous
#
# It separates PII printed in groups ("44 99 43") and equally separates
# unrelated payslip numbers sitting next to each other ("Period 09 2025").
# The digit-run pattern used to treat it as an intra-number separator,
# so it counted digits across independent numbers and refused benign
# payslips - a live 422 on a real ADP payslip. Both properties are
# checked here because fixing one by loosening the other is exactly the
# regression to guard against.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        # Adjacent-but-unrelated numbers - the false positive that fired.
        "Period 09 2025 Frequency Monthly",
        "Tax Period 09 Week 39 Gross 2500.00",
        # Hourly rates print to 3-5 dp; _CURRENCY_RE only matches exactly
        # 2, so these digits used to survive masking unexplained.
        "Std Hours 37.50 Rate 15.3846",
        "Overtime 12.5 Hours @ 23.0769",
        "Rate of Pay 9.5000 per hour",
        # Multi-column numeric tables, as ADP prints them.
        "NI Cat A Earnings 2500.00 1048.00 1452.00 116.16",
    ],
)
def test_gate_accepts_legitimate_payslip_numbers(payload):
    assert_safe_to_send(payload)  # must not raise


@pytest.mark.parametrize(
    "payload",
    [
        # Uniform digit groups - what PII looks like when printed in
        # groups. Caught by the split-group half of check 2, since
        # whitespace is no longer an intra-number separator.
        "Code 123 456 789 National Insurance 0.00",
        "Ref 1234 5678 9012 National Insurance 0.00",
        # Contiguous run - caught by the single-token half.
        "Some Internal Reference 123456789 National Insurance 0.00",
        "Unknown 987654321012 National Insurance 0.00",
    ],
)
def test_gate_still_refuses_unexplained_digits(payload):
    with pytest.raises(RedactionFailure):
        assert_safe_to_send(payload)


# --------------------------------------------------------------------------
# Unexplained identifiers are REDACTED, not left for the gate to refuse
#
# A 6-7 digit employee/payroll number sits in a gap between the specific
# patterns: too short for the 8-digit account number, no separators for
# the sort code. It used to survive redact() untouched and then trip the
# gate's digit-run check, refusing the whole document - which also means
# the only thing stopping that number being sent was the gate. Redacting
# it at source is both the safer outcome and the one that lets the
# payslip actually process.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,identifier",
    [
        ("Employee 123456 Gross Pay 2500.00", "123456"),
        ("Employee ID 1234567 Tax Code 1257L", "1234567"),
        ("Staff Number 123456 Net Pay 2000.00", "123456"),
        ("Clock Number 12345678901 Hours 37.50", "12345678901"),
    ],
)
def test_unexplained_identifier_is_redacted_and_then_passes_the_gate(line, identifier):
    redacted, _ = redact(line)
    assert identifier not in redacted
    payload = financial_lines_only(redacted)
    assert_safe_to_send(payload)  # must not raise


@pytest.mark.parametrize(
    "line,must_survive",
    [
        # Six-plus digits before the decimal point is still money, not an
        # identifier - the catch-all must not eat a large gross figure.
        ("Gross Pay 125000.00 Tax Code 1257L", "125000.00"),
        ("YTD Gross 1,234,567.89 Tax Code 1257L", "1,234,567.89"),
        ("Gross Pay 2500.00 Net Pay 1987.65", "2500.00"),
        # Dates must survive the catch-all too, in both orders.
        ("Pay Date 15/12/2025 Gross 2500.00", "15/12/2025"),
        ("Pay Date 2025-12-15 Gross 2500.00", "2025-12-15"),
    ],
)
def test_catch_all_does_not_eat_money_or_dates(line, must_survive):
    redacted, _ = redact(line)
    assert must_survive in redacted, f"{must_survive!r} was redacted: {redacted!r}"


# --------------------------------------------------------------------------
# Frequency read from a printed period label
#
# Plenty of payslips never print "Monthly" as a word - they print
# "Month 9". The prompt tells the model to return null rather than guess,
# so it correctly returns nothing, and without a frequency period_number
# can't be derived. That cascades: no period_number means
# _facts_from_extract() refuses, which surfaces to the user as "We could
# not complete every calculation". Reading "Month" beside a number is
# extraction, not invention - but it has to refuse anything ambiguous.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Month 9", "monthly"),
        ("Tax Month 09", "monthly"),
        ("Month No. 9", "monthly"),
        ("Pay Frequency Monthly", "monthly"),
        ("Week 39", "weekly"),
        ("Tax Week 39", "weekly"),
        ("Weekly", "weekly"),
    ],
)
def test_frequency_read_from_a_printed_label(text, expected):
    assert infer_frequency_from_label(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Names no unit - picking one would be the invented value the
        # whole confidence gate exists to prevent.
        "Period 9",
        # A date label, not a period number - must not read as weekly.
        "Week Ending 15/12/2025",
        # Contradictory evidence.
        "Month 9 Week 39",
        # Frequencies the engine has no rates for. The bare word "weekly"
        # inside these must not read as plain weekly - that would
        # calculate a 4-weekly payslip on weekly thresholds.
        "4 Weekly",
        "Fortnightly",
        "Bi-Weekly",
        "Two-weekly Pay",
        "Quarterly",
        # Nothing to read at all.
        "Pay Date 15/12/2025",
        "Annual Salary 30000",
    ],
)
def test_frequency_inference_refuses_anything_ambiguous(text):
    assert infer_frequency_from_label(text) is None


def test_printed_month_label_unblocks_period_number_and_the_calculation():
    """
    The whole cascade, end to end - this is the bug the user saw as two
    separate messages ("We could not complete every calculation" and
    "COULDN'T READ CONFIDENTLY: period.period_number"). They are one
    bug: the payslip prints a pay date and "Tax Month 9" but never the
    word "Monthly", so the model returns no frequency, so period_number
    can't be derived, so _facts_from_extract() refuses and the whole
    calculation is skipped.
    """
    text = (
        "Pay Date 15/12/2025 Tax Month 9\n"
        "Tax Code 1257L Income Tax 412.60\n"
        "National Insurance 198.16\n"
        "Total Gross Pay 2750.00\n"
        "Taxable Gross Pay 24750.00\n"
        "Net Pay 2139.24\n"
    )

    model_extract = _ModelExtract()
    model_extract.period.pay_date = date(2025, 12, 15)
    model_extract.period.frequency = None  # correctly returns nothing
    model_extract.period.period_number = None
    model_extract.tax_code.value = "1257L"
    model_extract.pay.gross_this_period = Decimal("2750.00")
    model_extract.pay.gross_ytd = Decimal("24750.00")
    model_extract.deductions.income_tax = Decimal("412.60")
    model_extract.deductions.national_insurance = Decimal("198.16")
    model_extract.deductions.ni_category = "A"
    model_extract.net_pay = Decimal("2139.24")

    pdf_bytes = _make_pdf_bytes(text.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.frequency == "monthly"
    assert result.period.period_number == 9  # 15 Dec 2025 -> month 9
    assert "period.period_number" not in result.unreadable_fields
    # The frequency is label-read, not model-read - say so downstream.
    assert any("period.frequency" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "model_pay_date,model_frequency",
    [
        (date(2025, 12, 15), "monthly"),  # model reads both
        (date(2025, 12, 15), None),  # model drops the frequency
        (None, "monthly"),  # model drops the pay date
        (None, None),  # model drops both
    ],
)
def test_period_number_is_stable_however_flaky_the_model_is(
    model_pay_date, model_frequency
):
    """
    The "works, but it sometimes shows up" report. Both pay_date and
    frequency gate period_number, which gates the whole calculation, and
    both used to come only from the model - so on an unchanged payslip
    the advisory appeared on some runs and not others. temperature is
    already pinned to 0 on both providers; that is not sufficient on its
    own, because a model still varies run to run. Reading both off the
    printed labels in code is what actually makes the result stable, so
    all four of these must produce identical output.
    """
    text = (
        "Pay Date 15/12/2025 Tax Month 9\n"
        "Tax Code 1257L Income Tax 412.60\n"
        "National Insurance 198.16\n"
        "Total Gross Pay 2750.00\n"
        "Taxable Gross Pay 24750.00\n"
        "Net Pay 2139.24\n"
    )

    model_extract = _ModelExtract()
    model_extract.period.pay_date = model_pay_date
    model_extract.period.frequency = model_frequency
    model_extract.tax_code.value = "1257L"
    model_extract.pay.gross_this_period = Decimal("2750.00")
    model_extract.pay.gross_ytd = Decimal("24750.00")
    model_extract.deductions.income_tax = Decimal("412.60")
    model_extract.deductions.national_insurance = Decimal("198.16")
    model_extract.deductions.ni_category = "A"
    model_extract.net_pay = Decimal("2139.24")

    pdf_bytes = _make_pdf_bytes(text.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.pay_date == date(2025, 12, 15)
    assert result.period.frequency == "monthly"
    assert result.period.period_number == 9
    assert "period.period_number" not in result.unreadable_fields


# --------------------------------------------------------------------------
# Tax year derivation
# --------------------------------------------------------------------------


def test_tax_year_before_april_boundary():
    assert _tax_year_for(date(2026, 3, 31)) == "2025/26"


def test_tax_year_on_april_boundary():
    assert _tax_year_for(date(2026, 4, 6)) == "2026/27"


def test_tax_year_just_before_april_boundary():
    assert _tax_year_for(date(2026, 4, 5)) == "2025/26"


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


def _extract_dict(**deductions_overrides):
    deductions = {
        "income_tax": Decimal("0.00"),
        "national_insurance": Decimal("0.00"),
        "pension_employee": None,
        "student_loan": None,
        "other": [],
    }
    deductions.update(deductions_overrides)
    return {
        "pay": {"gross_this_period": Decimal("583.55")},
        "net_pay": Decimal("583.55"),
        "deductions": deductions,
    }


def test_reconciles_true_when_the_real_sample_figures_add_up():
    assert _reconciles(_extract_dict(), unreadable=set()) is True


def test_reconciles_false_when_the_figures_do_not_add_up():
    extract_dict = _extract_dict(income_tax=Decimal("50.00"))
    assert _reconciles(extract_dict, unreadable=set()) is False


def test_reconciles_none_when_a_component_is_flagged_unreadable():
    extract_dict = _extract_dict()
    assert _reconciles(extract_dict, unreadable={"deductions.income_tax"}) is None


def test_reconciles_none_when_gross_or_net_missing():
    extract_dict = _extract_dict()
    extract_dict["net_pay"] = None
    assert _reconciles(extract_dict, unreadable=set()) is None


def test_reconciles_accounts_for_other_deductions():
    extract_dict = _extract_dict()
    extract_dict["deductions"]["other"] = [{"type": "union", "amount": Decimal("10.00")}]
    extract_dict["net_pay"] = Decimal("573.55")
    assert _reconciles(extract_dict, unreadable=set()) is True


# --------------------------------------------------------------------------
# extract_payslip - full pipeline, model call mocked
# --------------------------------------------------------------------------


def test_user_context_never_reaches_the_extraction_model():
    """
    only_job (and any other application metadata) is answered by the user
    in the UI, sent as a form field alongside the file, and consumed by
    analyse_payslip() AFTER extraction. It must never be part of the
    model payload.

    Structural, not incidental: extract_payslip() has no parameter for it
    to arrive through. This captures the exact string handed to the model
    and checks it against the PDF's own text, so adding a metadata
    parameter later would have to break this test to leak.
    """
    text = "\n".join(
        [
            "Pay Date: 28/08/2026",
            "Tax Code: 1257L M1",
            "Total Gross Pay 2,500.00 Net Pay 1,968.34",
        ]
    )
    captured: dict[str, str] = {}

    def _capture(payload: str) -> _ModelExtract:
        captured["payload"] = payload
        return _sample_model_extract()

    with patch("slyp.extraction._call_model", side_effect=_capture):
        extract_payslip(_make_pdf_bytes(text.splitlines()))

    payload = captured["payload"]
    for forbidden in ("only_job", "job_label", "true", "false", "not_sure"):
        assert forbidden not in payload.lower()

    # Everything sent came off the page, nothing was added to it.
    source_lines = set(text.splitlines())
    for line in payload.splitlines():
        assert line in source_lines

    # And there is no parameter to smuggle it through.
    import inspect

    assert set(inspect.signature(extract_payslip).parameters) == {
        "pdf_bytes",
        "filename",
    }


def _sample_model_extract() -> _ModelExtract:
    return _ModelExtract.model_validate(
        {
            "is_payslip": True,
            # None, not "Easy Gourmet Ltd": in reality the model never
            # sees the employer name at all (the allowlist drops that
            # line before the model call), so a real response would
            # always be null here. Left null so the pipeline tests below
            # prove employer_name comes from the redaction map, not from
            # the model happening to echo the right value back.
            "employer_name": None,
            "period": {
                "pay_date": "2026-03-31",
                "period_number": 12,
                "frequency": "monthly",
            },
            "tax_code": {"value": "1257L"},
            "pay": {
                "gross_this_period": "583.55",
                "gross_ytd": "854.07",
            },
            "deductions": {
                "income_tax": "0.00",
                "income_tax_ytd": "0.00",
                "national_insurance": "0.00",
                "national_insurance_ytd": "0.00",
                "ni_category": "A",
            },
            "net_pay": "583.55",
            "confidence": {
                "pay.gross_this_period": 0.99,
                "tax_code.value": 0.98,
                "net_pay": 0.99,
            },
            "unreadable_fields": [],
            "warnings": [],
        }
    )


def test_extract_payslip_derives_tax_year_and_reconciles_via_mocked_model():
    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())

    with patch("slyp.extraction._call_model", return_value=_sample_model_extract()):
        result = extract_payslip(pdf_bytes)

    assert result.period.tax_year == "2025/26"
    assert result.reconciles is True
    assert result.source.pages == 1
    # SAMPLE_TEXT has no "Employer:"-style label - "Easy Gourmet Ltd" is
    # just the first line, with no anchor. There is no fallback anymore
    # (see _find_employer_name), so this is honestly None rather than a
    # guess - even though a human reading the document could tell.
    assert result.employer_name is None
    assert "employer name was not confidently identified" in result.warnings


def test_extract_payslip_nulls_low_confidence_fields():
    model_extract = _sample_model_extract()
    model_extract.confidence["tax_code.value"] = 0.2  # below threshold

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.tax_code.value is None
    assert "tax_code.value" in result.unreadable_fields


def test_extract_payslip_raises_not_a_payslip_when_model_says_so():
    from slyp.extraction import NotAPayslip

    model_extract = _ModelExtract.model_validate({"is_payslip": False})
    pdf_bytes = _make_pdf_bytes(["Some unrelated document"])

    with patch("slyp.extraction._call_model", return_value=model_extract):
        with pytest.raises(NotAPayslip):
            extract_payslip(pdf_bytes)


# --------------------------------------------------------------------------
# derive_period_number
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pay_date,frequency,expected",
    [
        (date(2026, 4, 6), "monthly", 1),
        (date(2026, 5, 5), "monthly", 1),
        (date(2026, 5, 6), "monthly", 2),
        (date(2026, 3, 31), "monthly", 12),
        # matches what the real payslip printed - see slyp-phase3-prompt.md
        (date(2026, 2, 13), "weekly", 45),
        # weekly, either side of the 6 April boundary - the monthly cases
        # above cover this, but weekly's day-counting arithmetic is
        # different code and wasn't independently exercised here.
        (date(2026, 4, 6), "weekly", 1),
        (date(2026, 4, 5), "weekly", 53),
    ],
)
def test_derive_period_number(pay_date, frequency, expected):
    assert derive_period_number(pay_date, frequency) == expected


def test_derive_period_number_none_without_pay_date_or_frequency():
    assert derive_period_number(None, "monthly") is None
    assert derive_period_number(date(2026, 5, 5), None) is None


def test_extract_payslip_derives_period_number_even_when_model_omits_it():
    model_extract = _sample_model_extract()
    model_extract.period.period_number = None  # what 4 of 5 real payslips returned

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number == 12  # 31-Mar-2026, monthly
    assert result.confidence["period.period_number"] == 1.0
    assert "period.period_number" not in result.unreadable_fields


def test_extract_payslip_prefers_derived_period_number_over_model_and_warns():
    model_extract = _sample_model_extract()
    model_extract.period.period_number = 1  # deliberately wrong

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number == 12
    assert any("period.period_number" in w for w in result.warnings)
    assert any("1" in w and "12" in w for w in result.warnings)


def test_extract_payslip_never_guesses_a_frequency_to_derive_period_number():
    """
    The live-run failure this closes: frequency came back null, but
    period_number came back 9 at confidence 1.0 anyway - something
    assumed monthly and reported the guess as certain. With frequency
    unknown, period_number must be null and land in unreadable_fields,
    regardless of what the model itself reported for either field.
    """
    model_extract = _sample_model_extract()
    model_extract.period.frequency = None
    model_extract.period.period_number = 9
    model_extract.confidence["period.period_number"] = 1.0

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT_NO_FREQUENCY.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number is None
    assert "period.period_number" in result.unreadable_fields


def test_extract_payslip_does_not_derive_period_number_when_frequency_is_unreadable():
    """Same guard, reached the other way: frequency IS present but was
    already flagged unreadable (e.g. by a low confidence score) - it must
    not be trusted to derive from just because it isn't null."""
    model_extract = _sample_model_extract()
    model_extract.confidence["period.frequency"] = 0.1  # below threshold

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number is None
    assert "period.period_number" in result.unreadable_fields
    assert "period.frequency" in result.unreadable_fields


# --------------------------------------------------------------------------
# Printed-period-label fallback: no pay date to derive from, but the
# payslip prints an explicit period label the model read confidently.
# --------------------------------------------------------------------------


def test_extract_payslip_accepts_printed_period_label_when_no_pay_date_and_in_range():
    """
    The case the fallback exists for: a payslip that states its period as
    "Month 9" with no calendar pay date anywhere - frequency is
    confidently known, the label is a plausible value for that frequency,
    so it's accepted rather than refused, and marked distinctly from a
    derived value.
    """
    model_extract = _sample_model_extract()
    model_extract.period.pay_date = None
    model_extract.period.period_number = 9
    model_extract.confidence["period.period_number"] = 0.9

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT_NO_PAY_DATE.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number == 9
    assert "period.period_number" not in result.unreadable_fields
    # Left as the model's own reading, not promoted to 1.0 like a derived
    # value - this is what makes the two provenances distinguishable.
    assert result.confidence["period.period_number"] == 0.9
    assert any(
        "read directly from a printed period label" in w for w in result.warnings
    )


def test_extract_payslip_refuses_printed_period_label_out_of_range():
    """A monthly payslip claiming period 45 is not a plausible reading -
    refuse rather than accept an implausible label."""
    model_extract = _sample_model_extract()
    model_extract.period.pay_date = None
    model_extract.period.period_number = 45
    model_extract.confidence["period.period_number"] = 0.9

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT_NO_PAY_DATE.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number is None
    assert "period.period_number" in result.unreadable_fields
    assert not any(
        "read directly from a printed period label" in w for w in result.warnings
    )


def test_extract_payslip_refuses_printed_period_label_when_frequency_unconfirmed():
    """No pay date, and the period label is in-range for monthly - but
    frequency itself isn't confirmed, so there's no basis to judge
    plausibility against. Must refuse, not assume monthly."""
    model_extract = _sample_model_extract()
    model_extract.period.pay_date = None
    model_extract.period.frequency = None
    model_extract.period.period_number = 9
    model_extract.confidence["period.period_number"] = 0.9

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT_NO_PAY_DATE.replace('Pay Type Monthly', 'Pay Type').splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number is None
    assert "period.period_number" in result.unreadable_fields


def test_extract_payslip_pay_date_takes_precedence_over_printed_label():
    """Pay date present and derivable -> always wins, the fallback branch
    is never reached, even when the model's own printed-label reading
    would itself have been accepted (in range) if pay date were absent."""
    model_extract = _sample_model_extract()  # pay_date "2026-03-31", monthly -> derives to 12
    model_extract.period.period_number = 9  # plausible on its own, but wrong
    model_extract.confidence["period.period_number"] = 0.9

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number == 12
    assert result.confidence["period.period_number"] == 1.0  # derived, not label-read
    assert any("period.period_number" in w and "12" in w for w in result.warnings)
    assert not any(
        "read directly from a printed period label" in w for w in result.warnings
    )


def test_extract_payslip_label_and_derived_disagreeing_prefers_derived():
    """
    Same scenario as the precedence test above, framed the other way: the
    label and the derived value disagree, and there is no separate
    conflict-resolution path for that - pay date being present already
    means derivation runs and wins outright (see
    test_extract_payslip_prefers_derived_period_number_over_model_and_warns
    for the original version of this guarantee). The fallback only ever
    activates when derivation has nothing to work with in the first
    place, so "label vs derived" can only arise when pay date exists, at
    which point derived has already won before the fallback is even
    considered.
    """
    model_extract = _sample_model_extract()  # pay_date "2026-03-31", monthly -> derives to 12
    model_extract.period.period_number = 3  # disagrees with the derived value
    model_extract.confidence["period.period_number"] = 0.95

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT_NO_PAY_DATE.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.period.period_number == 12
    assert any("3" in w and "12" in w for w in result.warnings)


# --------------------------------------------------------------------------
# employer_name
# --------------------------------------------------------------------------


def test_find_employer_name_prefers_labelled_match():
    text = "Some Header\nEmployer: Acme Widgets Ltd\nGross Pay 100.00"
    assert _find_employer_name(text, RedactionMap()) == "Acme Widgets Ltd"


def test_find_employer_name_does_not_confuse_employer_nic_for_a_label():
    """
    Regression case: "Employer NIC 24.98" starts with the word "Employer"
    but is the employer's NI contribution figure, not an "Employer: Name"
    label - the label match requires a colon specifically to avoid this.
    """
    assert _find_employer_name(SAMPLE_TEXT, RedactionMap()) is None


def test_find_employer_name_has_no_fallback_for_an_unlabelled_document():
    """
    The old behaviour ("take the first line that isn't obviously a name,
    address or label") was deleted outright: on a live run against five
    real payslips it returned the EMPLOYEE's own name on two of them.
    There is no first-line guess anymore, labelled or not - an unlabelled
    document is honestly None.
    """
    text = "Acme Ltd\nGross 1.00"
    assert _find_employer_name(text, RedactionMap()) is None


def test_find_employer_name_rejects_a_candidate_that_is_actually_the_employee():
    """
    The guard: an "Employer:" label whose value is byte-for-byte the same
    as PII already caught elsewhere (here, the labelled employee name) is
    rejected rather than trusted - it's far more likely to be a
    mislabelled personal detail than a genuine coincidence.
    """
    text = "Employer: Jane Doe\nEmployee Name: Jane Doe\nGross Pay 100.00"
    _redacted, redaction_map = redact(text)
    assert redaction_map.employer_name is None


def test_extract_payslip_employer_name_none_on_an_unlabelled_document():
    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=_sample_model_extract()):
        result = extract_payslip(pdf_bytes)

    assert result.employer_name is None
    assert "employer name was not confidently identified" in result.warnings

    redacted, _ = redact(SAMPLE_TEXT)
    payload = financial_lines_only(redacted)
    assert "Easy Gourmet Ltd" not in payload


def test_extract_payslip_populates_employer_name_when_labelled():
    text_with_label = "Employer: Easy Gourmet Ltd\n" + SAMPLE_TEXT
    pdf_bytes = _make_pdf_bytes(text_with_label.splitlines())
    with patch("slyp.extraction._call_model", return_value=_sample_model_extract()):
        result = extract_payslip(pdf_bytes)

    assert result.employer_name == "Easy Gourmet Ltd"
    assert "employer name was not confidently identified" not in result.warnings

    redacted, _ = redact(text_with_label)
    payload = financial_lines_only(redacted)
    assert "Easy Gourmet Ltd" not in payload


# --------------------------------------------------------------------------
# unreadable_fields / confidence path normalisation
# --------------------------------------------------------------------------


def test_normalize_field_paths_resolves_bare_names_to_dotted():
    model_extract = _ModelExtract.model_validate(
        {
            "unreadable_fields": ["student_loan", "period.frequency"],
            "confidence": {"student_loan": 0.4, "pay.gross_this_period": 0.9},
        }
    )
    warnings: list[str] = []
    _normalize_field_paths(model_extract, warnings)

    assert set(model_extract.unreadable_fields) == {
        "deductions.student_loan",
        "period.frequency",
    }
    assert model_extract.confidence == {
        "deductions.student_loan": 0.4,
        "pay.gross_this_period": 0.9,
    }
    assert warnings == []


def test_normalize_field_paths_drops_unresolvable_paths_with_a_warning():
    model_extract = _ModelExtract.model_validate(
        {"unreadable_fields": ["some_made_up_field"], "confidence": {}}
    )
    warnings: list[str] = []
    _normalize_field_paths(model_extract, warnings)

    assert model_extract.unreadable_fields == []
    assert len(warnings) == 1
    assert "some_made_up_field" in warnings[0]


def test_extract_payslip_normalises_mixed_path_formats_end_to_end():
    model_extract = _sample_model_extract()
    model_extract.unreadable_fields = ["student_loan"]  # bare, not dotted

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert "deductions.student_loan" in result.unreadable_fields
    assert "student_loan" not in result.unreadable_fields


# --------------------------------------------------------------------------
# Ambiguity lowers confidence - only via ambiguous_fields, never by
# scanning warning text for keywords (that over-fired badly - see
# _cap_ambiguous_field_confidence's docstring).
# --------------------------------------------------------------------------


def test_cap_ambiguous_field_confidence_caps_only_named_fields():
    model_extract = _ModelExtract.model_validate(
        {
            "confidence": {"pay.gross_this_period": 0.85, "net_pay": 0.9},
            "ambiguous_fields": ["pay.gross_this_period"],
        }
    )
    _cap_ambiguous_field_confidence(model_extract)

    assert model_extract.confidence["pay.gross_this_period"] < _CONFIDENCE_THRESHOLD
    assert model_extract.confidence["net_pay"] == 0.9  # not named, untouched


def test_extract_payslip_moves_named_ambiguous_field_to_unreadable():
    """The live-run case this replaces: a warning naming a conflict sits
    next to a high (0.85) confidence score for the field it's about. That
    combination only moves the field into unreadable_fields now if the
    model also named it in ambiguous_fields."""
    model_extract = _sample_model_extract()
    model_extract.confidence["pay.gross_this_period"] = 0.85
    model_extract.ambiguous_fields = ["pay.gross_this_period"]
    model_extract.warnings = [
        "Total Earnings and Gross Pay figures disagree on this payslip; used Gross Pay"
    ]

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert "pay.gross_this_period" in result.unreadable_fields
    assert result.pay.gross_this_period is None


def test_extract_payslip_explanatory_warning_without_ambiguous_fields_stays_confident():
    """
    The exact regression: the model explains a genuinely useful, high-
    confidence finding ("Tax code 0T M1 is an emergency/non-cumulative
    code") in a warning. That must NOT null the field out - it's the
    single most useful insight the product surfaces, not an expression of
    doubt. Only ambiguous_fields can do that, and this response leaves it
    empty.
    """
    model_extract = _sample_model_extract()
    model_extract.warnings = ["Tax code 0T M1 is an emergency/non-cumulative code"]
    assert model_extract.ambiguous_fields == []

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=model_extract):
        result = extract_payslip(pdf_bytes)

    assert result.tax_code.value == "1257L"
    assert "tax_code.value" not in result.unreadable_fields


def test_normalize_field_paths_also_normalises_ambiguous_fields():
    model_extract = _ModelExtract.model_validate(
        {"ambiguous_fields": ["gross_this_period"], "confidence": {}}
    )
    warnings: list[str] = []
    _normalize_field_paths(model_extract, warnings)

    assert model_extract.ambiguous_fields == ["pay.gross_this_period"]


# --------------------------------------------------------------------------
# filename
# --------------------------------------------------------------------------


def test_extract_payslip_populates_source_filename_when_given():
    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=_sample_model_extract()):
        result = extract_payslip(pdf_bytes, filename="march-payslip.pdf")

    assert result.source.filename == "march-payslip.pdf"


def test_extract_payslip_source_filename_defaults_to_none():
    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
    with patch("slyp.extraction._call_model", return_value=_sample_model_extract()):
        result = extract_payslip(pdf_bytes)

    assert result.source.filename is None


# --------------------------------------------------------------------------
# OpenAI retry path: the second request is not a second chance to leak
# --------------------------------------------------------------------------


def test_openai_retry_resends_the_same_redacted_payload():
    """
    The provider rejects function tools unless reasoning_effort is set to
    'none', so the first request 400s and a second is sent. Redaction,
    the allowlist and the gate all run ONCE, in extract_payslip(), before
    either request exists - so what has to hold is that the retry sends
    the identical already-sanitised string and adds nothing to it.

    Pinned because "retry the request" is exactly the kind of code that
    later grows a "with a bit more context this time".
    """
    import slyp.extraction as extraction

    text = "\n".join(
        [
            "Employee Name: Jo Bloggs",
            "NI Number AB 12 34 56 C National Insurance 0.00",
            "Pay Date: 28/08/2026",
            "Total Gross Pay 1,000.00 Net Pay 900.00",
        ]
    )

    sent: list[dict] = []

    class _FakeCompletions:
        def create(self, **params):
            sent.append(params)
            if "reasoning_effort" not in params:
                raise extraction.openai.BadRequestError(
                    "Function tools with reasoning_effort are not supported",
                    response=_fake_http_response(),
                    body=None,
                )
            return _fake_openai_response()

    class _FakeClient:
        def __init__(self):
            self.chat = type("chat", (), {"completions": _FakeCompletions()})()

    pdf_bytes = _make_pdf_bytes(text.splitlines())

    with patch.object(extraction, "_MODEL_PROVIDER", "openai"), patch.object(
        extraction, "_OPENAI_NEEDS_REASONING_EFFORT_NONE", False
    ), patch.object(extraction.openai, "OpenAI", _FakeClient):
        extraction.extract_payslip(pdf_bytes)
        assert len(sent) == 2, "expected one rejected request and one retry"

        # The answer doesn't change between calls, so the doomed first
        # attempt must not be repeated for the rest of the process.
        extraction.extract_payslip(pdf_bytes)
        assert len(sent) == 3, "second upload should not repeat the 400"
        assert sent[2]["reasoning_effort"] == "none"

    first_user = sent[0]["messages"][1]["content"]
    retry_user = sent[1]["messages"][1]["content"]

    # Identical, and sanitised - not the raw document.
    assert first_user == retry_user
    for payload in (first_user, retry_user):
        assert "Jo Bloggs" not in payload
        assert "AB 12 34 56 C" not in payload
        assert "[NI]" in payload

    # The retry differs by exactly one parameter.
    assert set(sent[1]) - set(sent[0]) == {"reasoning_effort"}
    assert sent[1]["reasoning_effort"] == "none"


def _fake_http_response():
    """Enough of an httpx response for openai.BadRequestError to build."""
    return SimpleNamespace(
        request=SimpleNamespace(),
        status_code=400,
        headers={},
    )


def _fake_openai_response():
    """Minimal stand-in for an OpenAI chat completion carrying our tool call."""
    import json as _json

    extract = _sample_model_extract()
    arguments = _json.dumps(_json.loads(extract.model_dump_json()))
    function = type("fn", (), {"name": "record_payslip_extract", "arguments": arguments})()
    tool_call = type("tc", (), {"function": function})()
    message = type("msg", (), {"tool_calls": [tool_call]})()
    choice = type("choice", (), {"message": message})()
    return type("response", (), {"choices": [choice]})()


# --------------------------------------------------------------------------
# Previous-employment YTD detection
# --------------------------------------------------------------------------
#
# Decides whether the allowance-used figure may be shown at all, so it is
# read in code from the document's own labels rather than asked of the
# model - see analysis.build_allowance_usage().


@pytest.mark.parametrize(
    "line",
    [
        "Previous Employment 5,000.00",
        "Previous Employer Pay 5,000.00",
        "Prev Employment 5,000.00",
        "Prev. Employer 5,000.00",
        "Pay from previous employment 5,000.00",
        "Previous Pay 5,000.00",
        "Previous Taxable Pay 5,000.00",
        "P45 Pay 5,000.00",
        "Brought Forward 5,000.00",
        "B/Fwd 5,000.00",
        "Taxable Pay in Previous Employment 5,000.00",
    ],
)
def test_previous_employment_line_is_detected(line):
    assert has_previous_employment_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "Gross Pay YTD 7,500.00",
        "Total Gross Pay 2,500.00",
        "This Employment 7,500.00",
        "Employment Type Permanent",
        "Previous address on file",
    ],
)
def test_ordinary_payslip_lines_are_not_mistaken_for_it(line):
    assert has_previous_employment_line(line) is False


# --------------------------------------------------------------------------
# DD/MM/YY - the one date shape that collides with the sort-code pattern
# --------------------------------------------------------------------------
#
# DOCUMENTS AN ACCEPTED LOSS. These assertions describe what the pipeline
# does, not what anyone wants it to do.
#
# _SORT_CODE_RE is \b\d{2}[-\s/]\d{2}[-\s/]\d{2}\b - three two-digit groups.
# A date with two digits in the day, month AND year is exactly that shape,
# so "15/12/25" is redacted to [BANK] and the date is gone before the model
# sees it. A four-digit year is what saves DD/MM/YYYY: the trailing \b
# fails against the year's fourth digit.
#
# redact() explains why the sort-code pattern gets no date exemption: a
# 6-digit date and a real sort-code-with-slashes bypass (F6) are
# indistinguishable by shape, and exempting one reopens the other. Payslips
# overwhelmingly print 4-digit years, so losing the uncommon 2-digit case is
# the accepted trade.
#
# This was untested until now. The existing date-survival fixtures are
# 15/12/2025, 15-12-2025, 5/3/25 and 2025-12-15 - and 5/3/25 slips past the
# collision only because single-digit day and month are too few digits for
# the pattern to reach. Nothing covered the two-digit-everything case, which
# is the only one that actually collides.


@pytest.mark.parametrize(
    "two_digit_year_date",
    [
        "15/12/25",  # DD/MM/YY, slashes
        "15-12-25",  # DD-MM-YY, hyphens
        "20/07/26",
        "01/01/26",
    ],
)
def test_two_digit_year_date_is_lost_to_the_sort_code_pattern(two_digit_year_date):
    """Accepted loss, pinned so it cannot change silently in either
    direction: if this ever starts passing, the sort-code pattern has been
    narrowed and F6 needs re-checking."""
    redacted, _ = redact(f"Pay Date {two_digit_year_date} Gross 2500.00")

    assert two_digit_year_date not in redacted
    assert "[BANK]" in redacted
    # The money on the same line must not be collateral.
    assert "2500.00" in redacted


@pytest.mark.parametrize(
    "four_digit_year_date",
    ["15/12/2025", "15-12-2025", "20/07/2026", "2025-12-15"],
)
def test_four_digit_year_date_is_not_touched_by_the_sort_code_pattern(
    four_digit_year_date,
):
    """The other side of the same boundary, asserted against _SORT_CODE_RE
    directly rather than through redact(), so it cannot be satisfied by some
    other pattern happening to spare the date."""
    assert _SORT_CODE_RE.search(four_digit_year_date) is None

    redacted, _ = redact(f"Pay Date {four_digit_year_date} Gross 2500.00")
    assert four_digit_year_date in redacted


def test_single_digit_day_and_month_dodges_the_collision_by_length():
    """Why 5/3/25 was never caught by the fixtures above: the sort-code
    pattern needs two digits in each group, and this has one."""
    assert _SORT_CODE_RE.search("5/3/25") is None

    redacted, _ = redact("Pay Date 5/3/25 Gross 2500.00")
    assert "5/3/25" in redacted


# --------------------------------------------------------------------------
# A sort code never spans a line break
# --------------------------------------------------------------------------
#
# _SORT_CODE_RE used [-\s/] as its separator, and \s matches \n. On a
# work-record table with date-first rows that let it match '46\n20/07' -
# the pence of one row's total, the line break, and the next row's DD/MM.
# redact() SUBSTITUTES over its matches, so the newline went with it and
# three rows collapsed into one line reading "38.[BANK]/2026 ES602
# Repair...", destroying a total and a date and welding unrelated columns
# together.
#
# The merge was ours, not pdfplumber's - the extracted text still had its
# line breaks. Separator is now a literal space, hyphen or slash.


def test_sort_code_pattern_does_not_span_a_line_break():
    """The reported failure, pinned by name. If this regresses, a payslip
    with a numeric table silently loses rows again."""
    two_rows = "19/07/2026 ES601 Install 2.50 15.3846 38.46\n20/07/2026 ES602 Repair 1.75 15.3846 26.92"

    for match in _SORT_CODE_RE.finditer(two_rows):
        assert "\n" not in match.group(0), (
            f"sort-code pattern matched across a line break: {match.group(0)!r}"
        )


def test_redaction_does_not_weld_table_rows_together():
    """The consequence, asserted on line count rather than on the pattern -
    a different pattern developing the same fault would fail this too."""
    rows = "\n".join(
        f"{day}/07/2026 ES60{i} Install 2.50 15.3846 3{i}.46"
        for i, day in enumerate((19, 20, 21, 22), start=1)
    )
    redacted, _ = redact(rows)

    assert len(redacted.splitlines()) == len(rows.splitlines())
    assert "[BANK]" not in redacted
    for day in (19, 20, 21, 22):
        assert f"{day}/07/2026" in redacted


@pytest.mark.parametrize(
    "sort_code",
    ["12-34-56", "12 34 56", "12/34/56", "12-34/56", "12 34-56"],
)
def test_real_sort_codes_are_still_caught_on_one_line(sort_code):
    """The fix narrows the separator class, so every genuine separator has
    to keep working. F6 was a sort code getting through; that must not
    reopen."""
    assert _SORT_CODE_RE.search(sort_code) is not None

    redacted, _ = redact(f"Sort Code {sort_code} Account 12345678")
    assert sort_code not in redacted
    assert "[BANK]" in redacted


# --------------------------------------------------------------------------
# A label's value must be on the label's own line
# --------------------------------------------------------------------------
#
# _NAME_LABEL_RE and _ADDRESS_LABEL_RE used \s* between the label and the
# captured value, and \s matches \n. A bare "Name" or "Address" header -
# which is how both are usually printed when the value sits underneath -
# let the pattern eat the line break and capture the whole of the NEXT line
# as the value. On a payslip that next line is routinely figures, so the
# label swallowed a row of pay data and welded it to itself.
#
# Same fault as the sort-code cross-line match, one field over, and pinned
# the same way: on line count, so a different pattern developing the same
# fault fails these too.


@pytest.mark.parametrize("label", ["Name", "Employee Name", "Address", "Home Address"])
def test_bare_label_header_does_not_swallow_the_following_line(label):
    text = f"{label}\nBasic Pay 1,842.00  Income Tax 214.90"

    redacted, _ = redact(text)

    assert len(redacted.splitlines()) == 2, (
        f"{label!r} header consumed the line break: {redacted!r}"
    )
    assert "1,842.00" in redacted
    assert "214.90" in redacted


@pytest.mark.parametrize(
    ("labelled", "expected_token"),
    [
        ("Employee Name: Mr K Sample", "[NAME]"),
        ("Name: A Sample", "[NAME]"),
        ("Name   :   Jonathan Ashworth-Pike", "[NAME]"),
        ("Employee Name Mr K Sample", "[NAME]"),
        ("Address: 14 Marlborough Crescent", "[ADDRESS]"),
        ("Home Address:  Flat 2, 14 High St", "[ADDRESS]"),
        ("Address 14 Marlborough Crescent, Leeds", "[ADDRESS]"),
    ],
)
def test_a_labelled_value_on_the_same_line_is_still_redacted(labelled, expected_token):
    """The fix narrows the separator, so every same-line spacing that
    worked before has to keep working - including tabs, extra spaces and
    no colon at all."""
    redacted, _ = redact(labelled)

    assert expected_token in redacted
    assert labelled.split(":")[-1].strip() not in redacted


def test_tab_separated_label_and_value_still_redacted():
    """[ \t] not [ ] - a PDF text layer can put a tab between the two."""
    redacted, _ = redact("Employee Name:\tMr K Sample")

    assert "[NAME]" in redacted
    assert "Mr K Sample" not in redacted


# --------------------------------------------------------------------------
# _DATE_RE must not mask across a line break
# --------------------------------------------------------------------------
#
# Unlike the label and sort-code faults, this one failed in the UNSAFE
# direction. _DATE_RE has two jobs: financial_lines_only() calls it per
# line, where a cross-line match is impossible, but
# _mask_known_safe_numbers() runs it over the whole payload with .sub(" ")
# to remove digits a payslip legitimately explains, before the gate looks
# for ones it does not.
#
# With [-\s] the month-name alternative could match across a newline and
# mask away the last group of a group-printed digit sequence, leaving two
# groups where there had been three - so _SPLIT_DIGIT_GROUPS_RE no longer
# fired and the gate passed digits it refuses when they sit on one line.


@pytest.mark.parametrize(
    "kept_line",
    [
        "Gross 2,500.00 Code 123 4567 89",
        "Net Pay 1,531.58 Code 1234 567 89",
    ],
)
def test_month_name_on_the_next_line_does_not_unmask_grouped_digits(kept_line):
    """The leak, pinned by name.

    The digits have to sit on a line the allowlist KEEPS (so it carries a
    currency amount) and at the END of it, with a month name starting the
    line below - that is the only shape where the mask could reach across.
    """
    text = f"{kept_line}\nMar 2026 Net 1,531.58"

    redacted, _ = redact(text)
    filtered = financial_lines_only(redacted)

    with pytest.raises(RedactionFailure):
        assert_safe_to_send(filtered)


def test_date_pattern_does_not_match_across_a_line_break():
    """The mechanism, asserted on the pattern itself."""
    for match in _DATE_RE.finditer("Total 89\nMar 2026 Gross 2,500.00"):
        assert "\n" not in match.group(0), (
            f"date pattern matched across a line break: {match.group(0)!r}"
        )


@pytest.mark.parametrize(
    "written_date",
    ["15 Jan 2026", "15-Jan-2026", "1st Jan 2026", "15 January 2026",
     "28 Aug 26", "15\tJan\t2026"],
)
def test_month_name_dates_are_still_recognised_on_one_line(written_date):
    """The fix narrows the separator, so every same-line form has to keep
    working - the allowlist must keep the line, and the gate must still
    mask the digits as explained rather than flagging them."""
    line = f"Pay Date {written_date}"

    assert financial_lines_only(line).strip() != ""
    assert not any(c.isdigit() for c in _mask_known_safe_numbers(line))
