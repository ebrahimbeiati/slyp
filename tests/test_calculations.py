"""
Tests for the calculation layer.

These fail right now because the functions are stubs. Making them pass is
the job. Add more cases as you go, especially odd ones.

Run with:  pytest -q

IMPORTANT: the expected numbers marked TODO are placeholders. Work each
one out by hand from the gov.uk figures, then check it against an online
PAYE calculator. If you and the calculator disagree, find out why before
moving on — do not just change the test to match your code.
"""

from decimal import Decimal

import pytest

from slyp.calculations import (
    annualise,
    income_tax_due,
    national_insurance_due,
    parse_tax_code,
    student_loan_due,
)
from slyp.types import PayPeriodFacts, UnsupportedPayslip


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


@pytest.mark.parametrize("raw", ["1257L W1", "1257L M1", "1257LX", "1257L X"])
def test_emergency_suffixes_are_non_cumulative(raw):
    code = parse_tax_code(raw)
    assert code.cumulative is False
    assert code.is_emergency_basis is True
    assert code.free_pay_annual == Decimal("12570")


def test_k_code_is_a_negative_allowance():
    code = parse_tax_code("K475")
    assert code.kind == "K"
    assert code.free_pay_annual == Decimal("-4750")


def test_scottish_prefix_is_recorded():
    code = parse_tax_code("S1257L")
    assert code.region == "S"


def test_lowercase_and_spacing_are_handled():
    assert parse_tax_code(" br ").kind == "BR"


def test_nt_is_unsupported():
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("NT")


def test_nonsense_is_unsupported():
    with pytest.raises(UnsupportedPayslip):
        parse_tax_code("BANANA")


# --------------------------------------------------------------------------
# 2. national_insurance_due  — do this second
# --------------------------------------------------------------------------

def test_no_ni_below_primary_threshold():
    assert national_insurance_due(Decimal("500"), "monthly") == Decimal("0")


def test_ni_at_main_rate():
    # £2,000/month. TODO: work out by hand from the gov.uk thresholds.
    result = national_insurance_due(Decimal("2000"), "monthly")
    assert result == Decimal("76.16")


def test_ni_weekly_uses_weekly_thresholds():
    # £400/week. TODO: expected figure.
    result = national_insurance_due(Decimal("400"), "weekly")
    assert result == Decimal("12.64")


def test_ni_above_upper_earnings_limit():
    # £6,000/month: main rate up to the UEL, then 2% above. TODO.
    result = national_insurance_due(Decimal("6000"), "monthly")
    assert result == Decimal("287.50")


def test_other_ni_categories_unsupported():
    with pytest.raises(UnsupportedPayslip):
        national_insurance_due(Decimal("2000"), "monthly", category="C")


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
    # £2,000 in month 1 on 1257L. TODO: expected figure.
    assert income_tax_due(_facts("2000", "2000", "1257L")) == Decimal("TODO")


def test_br_code_taxes_every_pound():
    # £476 on BR: 20% of the lot, no allowance.
    assert income_tax_due(_facts("476", "476", "BR")) == Decimal("95.20")


def test_non_cumulative_ignores_the_year_so_far():
    # Same period pay, big year to date, W1 basis: the year is ignored,
    # so this should equal the month 1 cumulative figure for the same pay.
    cumulative = income_tax_due(_facts("2000", "2000", "1257L", period=1))
    non_cumulative = income_tax_due(_facts("2000", "16000", "1257L W1", period=8))
    assert non_cumulative == cumulative


def test_zero_pay_period():
    assert income_tax_due(_facts("0", "5000", "1257L", period=6)) == Decimal("0")


def test_never_returns_negative():
    # A refund situation must come back as zero, not a negative number.
    assert income_tax_due(_facts("0", "1000", "1257L", period=10)) >= Decimal("0")


# --------------------------------------------------------------------------
# 4. student_loan_due
# --------------------------------------------------------------------------

def test_no_student_loan_below_threshold():
    assert student_loan_due(Decimal("1000"), "2", "monthly") == Decimal("0")


def test_student_loan_plan_2():
    # £3,000/month. TODO: expected figure, rounded down to a whole pound.
    assert student_loan_due(Decimal("3000"), "2", "monthly") == Decimal("TODO")


def test_student_loan_rounds_down_to_whole_pounds():
    result = student_loan_due(Decimal("3000"), "2", "monthly")
    assert result == result.to_integral_value()


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
