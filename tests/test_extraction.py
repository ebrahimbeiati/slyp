from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from slyp.extraction import (
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

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
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

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
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

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
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

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
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

    pdf_bytes = _make_pdf_bytes(SAMPLE_TEXT.splitlines())
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
