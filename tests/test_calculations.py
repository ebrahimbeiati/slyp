"""
Tests for the calculation layer.

Run with:  pytest -q
"""

from decimal import Decimal

import pytest

from slyp.calculations import (
    annualise,
    income_tax_due,
    national_insurance_due,
    parse_tax_code,
    student_loan_due,
    validate_tax_year,
)
from slyp.types import PayPeriodFacts, UnsupportedPayslip


# --------------------------------------------------------------------------
# 0. validate_tax_year
# --------------------------------------------------------------------------

def test_validate_tax_year_accepts_the_supported_year():
    validate_tax_year("2026/27")  # must not raise


def test_validate_tax_year_refuses_a_prior_year():
    with pytest.raises(UnsupportedPayslip):
        validate_tax_year("2025/26")


def test_validate_tax_year_refuses_when_undeterminable():
    with pytest.raises(UnsupportedPayslip):
        validate_tax_year(None)


# --------------------------------------------------------------------------
# 1. parse_tax_code  — start here
# --------------------------------------------------------------------------

def test_standard_code():
    code = parse_tax_code("1257L")
    assert code.kind == "standard"
    assert code.free_pay_annual == Decimal("12570")
    assert code.cumulative is True
    assert code.region == "UK"


def test_br_code_gives_no_allowance():
    code = parse_tax_code("BR")
    assert code.kind == "BR"
    assert code.free_pay_annual == Decimal("0")
    assert code.grants_allowance is False


def test_zero_t_code():
    code = parse_tax_code("0T")
    assert code.kind == "0T"
    assert code.free_pay_annual == Decimal("0")


def test_nt_code_is_supported_and_zero_rated():
    # NT is genuinely "no tax", not out of scope — distinct from a code
    # that we refuse to calculate at all.
    code = parse_tax_code("NT")
    assert code.kind == "NT"
    assert code.free_pay_annual == Decimal("0")


@pytest.mark.parametrize("raw", ["1257L W1", "1257L M1", "1257LX", "1257L X"])
def test_emergency_suffixes_are_non_cumulative(raw):
    code = parse_tax_code(raw)
    assert code.cumulative is False
    assert code.is_emergency_basis is True
    assert code.free_pay_annual == Decimal("12570")


def test_k_code_is_unsupported():
    # K codes add notional pay and carry a regulatory limit — refuse
    # rather than approximate.
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("K475")


def test_scottish_prefix_is_unsupported():
    # Rest-of-UK bands would be confidently wrong for a Scottish code.
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("S1257L")


def test_welsh_prefix_is_unsupported():
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("C1257L")


def test_lowercase_and_spacing_are_handled():
    assert parse_tax_code(" br ").kind == "BR"


def test_nonsense_is_unsupported():
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("BANANA")


# --------------------------------------------------------------------------
# 2. national_insurance_due  — do this second
# --------------------------------------------------------------------------

def test_no_ni_below_primary_threshold():
    assert national_insurance_due(Decimal("500"), "monthly") == Decimal("0")


def test_ni_at_main_rate():
    # £2,000/month. PT is £1,048. (2000 - 1048) * 8% = 76.16.
    result = national_insurance_due(Decimal("2000"), "monthly")
    assert result == Decimal("76.16")


def test_ni_weekly_uses_weekly_thresholds():
    # £400/week. PT is £242. (400 - 242) * 8% = 12.64.
    result = national_insurance_due(Decimal("400"), "weekly")
    assert result == Decimal("12.64")


def test_ni_above_upper_earnings_limit():
    # £6,000/month: main rate up to the UEL (£4,189), then 2% above.
    # (4189 - 1048) * 8% = 251.28. (6000 - 4189) * 2% = 36.22. Total 287.50.
    result = national_insurance_due(Decimal("6000"), "monthly")
    assert result == Decimal("287.50")


def test_unrecognised_ni_category_unsupported():
    # "C" is a real, supported category (no employee NI) — this needs a
    # letter that genuinely isn't in the table.
    with pytest.raises(UnsupportedPayslip):
        national_insurance_due(Decimal("2000"), "monthly", ni_category="Q")


# --------------------------------------------------------------------------
# 3. income_tax_due
# --------------------------------------------------------------------------

def _facts(gross, ytd, code, period=1, frequency="monthly"):
    return PayPeriodFacts(
        gross_this_period=Decimal(gross),
        gross_ytd=Decimal(ytd),
        tax_code=parse_tax_code(code),
        period_number=period,
        frequency=frequency,
    )


def test_no_tax_when_under_the_allowance():
    # £800/month on a normal code: under one month's allowance, so no tax.
    assert income_tax_due(_facts("800", "800", "1257L")) == Decimal("0")


def test_basic_rate_cumulative():
    # £2,000 in month 1 on 1257L.
    # Free pay to date = 12570 / 12 * 1 = 1047.50.
    # Taxable to date  = 2000 - 1047.50 = 952.50.
    # Tax to date       = 952.50 * 20% = 190.50.
    # Period 1: nothing to subtract, so tax this period = 190.50.
    assert income_tax_due(_facts("2000", "2000", "1257L")) == Decimal("190.50")


def test_br_code_taxes_every_pound():
    # £476 on BR: 20% of the lot, no allowance.
    assert income_tax_due(_facts("476", "476", "BR")) == Decimal("95.20")


def test_nt_code_always_zero():
    assert income_tax_due(_facts("5000", "5000", "NT")) == Decimal("0")


def test_non_cumulative_ignores_the_year_so_far():
    # Same period pay, big year to date, W1 basis: the year is ignored,
    # so this should equal the month 1 cumulative figure for the same pay.
    # Free pay this period = 12570 / 12 = 1047.50.
    # Taxable this period  = 2000 - 1047.50 = 952.50.
    # Tax this period        = 952.50 * 20% = 190.50 — same as cumulative
    # month 1, because a single month's slice of the allowance is the same
    # either way.
    cumulative = income_tax_due(_facts("2000", "2000", "1257L", period=1))
    non_cumulative = income_tax_due(_facts("2000", "16000", "1257L W1", period=8))
    assert non_cumulative == cumulative == Decimal("190.50")


def test_zero_pay_period():
    assert income_tax_due(_facts("0", "5000", "1257L", period=6)) == Decimal("0")


def test_never_returns_negative():
    # A refund situation must come back as zero, not a negative number.
    assert income_tax_due(_facts("0", "1000", "1257L", period=10)) >= Decimal("0")


def test_scottish_code_trips_the_gate_not_a_calculation():
    # Refusal has to happen at parse time, before a PayPeriodFacts can even
    # be built — there is no calculation to run on a code we don't support.
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("S1257L")


def test_k_code_trips_the_gate_not_a_calculation():
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("K475")


# --------------------------------------------------------------------------
# 4. student_loan_due
# --------------------------------------------------------------------------

def test_no_student_loan_below_threshold():
    assert student_loan_due(Decimal("1000"), "monthly", "2") == Decimal("0")


def test_student_loan_plan_2():
    # £3,000/month, Plan 2 threshold £2,448.75.
    # (3000 - 2448.75) * 9% = 49.6125, floored to a whole pound = 49.
    assert student_loan_due(Decimal("3000"), "monthly", "2") == Decimal("49")


def test_student_loan_rounds_down_to_whole_pounds():
    result = student_loan_due(Decimal("3000"), "monthly", "2")
    assert result == result.to_integral_value()


def test_student_loan_none_plan_is_zero():
    assert student_loan_due(Decimal("3000"), "monthly", None) == Decimal("0")


# --------------------------------------------------------------------------
# 5. annualise
# --------------------------------------------------------------------------

def test_annualise_month_one():
    # £1,000 in month 1: £1,000 + 11 more months of it.
    assert annualise(Decimal("1000"), Decimal("1000"), 1, "monthly") == Decimal("12000")


def test_annualise_mid_year():
    # £1,000 in month 6, £5,500 so far (a lighter start to the year).
    assert annualise(Decimal("1000"), Decimal("5500"), 6, "monthly") == Decimal("11500")


def test_annualise_weekly():
    assert annualise(Decimal("200"), Decimal("200"), 1, "weekly") == Decimal("10400")


# --------------------------------------------------------------------------
# 6. input validation
# --------------------------------------------------------------------------

def test_period_number_out_of_range():
    with pytest.raises(ValueError):
        _facts("1000", "1000", "1257L", period=13)


def test_ytd_must_include_this_period():
    with pytest.raises(ValueError):
        _facts("1000", "500", "1257L")
