"""
Tests for the calculation layer.

Run with:  pytest -q
"""

from decimal import Decimal

import pytest

from slyp import calculations
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


@pytest.mark.parametrize("tax_year", ["2025/26", "2024/25"])
def test_validate_tax_year_refuses_a_prior_year(tax_year):
    with pytest.raises(UnsupportedPayslip):
        validate_tax_year(tax_year)


def test_validate_tax_year_refuses_when_undeterminable():
    """None refuses rather than assuming the current year - a payslip
    with no readable date is exactly where that guess would be least
    likely to be noticed."""
    with pytest.raises(UnsupportedPayslip):
        validate_tax_year(None)


def test_only_one_tax_year_is_supported_while_the_rates_are_single_valued():
    """
    Pins the invariant that makes the refusal safe: the rate constants in
    this module hold one year's values, so SUPPORTED_TAX_YEARS must hold
    exactly one year. Adding a second without making the constants
    year-aware would run older payslips through this year's student loan
    thresholds - wrong for plans 1, 2 and 4.
    """
    assert calculations.SUPPORTED_TAX_YEARS == frozenset({calculations.TAX_YEAR})


def test_the_tax_year_guard_has_no_bypass_flag():
    """A constant that switches a correctness guard off is exactly the
    kind of thing that survives into production. It was removed; keep it
    removed."""
    assert not hasattr(calculations, "ENFORCE_SUPPORTED_TAX_YEAR")


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


# --------------------------------------------------------------------------
# 7. £100,000 Personal Allowance taper  —  FR-04
# --------------------------------------------------------------------------
#
# The engine does not model the taper (allowance withdrawn £1 for every £2
# above £100,000). It must therefore REFUSE past the threshold rather than
# apply an allowance the taxpayer does not have.
#
# The guard used to live in annual_income_tax(), which had zero callers, so
# it protected nothing. These tests pin it to the live path.


def test_the_150k_repro_from_the_final_report_refuses():
    """FR-04, verify/FINAL_REPORT.md.

    A CORRECT £150,000 payslip - £12,500/month, month 12, 1257L, taxed
    exactly as HMRC would with a fully tapered (zero) allowance - used to
    come back with a finding claiming £678.37 of income tax had been
    under-deducted, because the engine granted the full £12,570 allowance.

    Named after the repro so it cannot be quietly retired.
    """
    facts = _facts("12500.00", "150000.00", "1257L", period=12)

    with pytest.raises(UnsupportedPayslip) as excinfo:
        income_tax_due(facts)

    # The message must name the actual reason, not just "unsupported".
    assert "100,000" in str(excinfo.value)
    assert "Personal Allowance" in str(excinfo.value)


def test_just_under_the_taper_threshold_still_calculates():
    """£99,996/yr (£8,333/month) must be answered normally - the guard has
    to refuse high earners without refusing ordinary payslips."""
    facts = _facts("8333.00", "99996.00", "1257L", period=12)

    tax = income_tax_due(facts)

    assert tax > Decimal("0")


def test_just_over_the_taper_threshold_refuses():
    """£100,008/yr - £12 over - must refuse. Pins the boundary itself, not
    just a comfortably-large number."""
    facts = _facts("8334.00", "100008.00", "1257L", period=12)

    with pytest.raises(UnsupportedPayslip):
        income_tax_due(facts)


def test_exactly_at_the_threshold_still_calculates():
    """£100,000 exactly is NOT above the threshold - the taper starts
    above it, so this must not refuse.

    Final period, so the projection is the year-to-date figure itself:
    annualise() adds this period's gross for the periods REMAINING, and at
    period 12 there are none.
    """
    facts = _facts("8333.33", "100000.00", "1257L", period=12)

    assert calculations.annualise(
        Decimal("8333.33"), Decimal("100000.00"), 12, "monthly"
    ) == Decimal("100000.00")
    assert income_tax_due(facts) > Decimal("0")


def test_taper_guard_applies_on_the_cumulative_path():
    """The path the FR-04 repro took: a plain 1257L code."""
    facts = _facts("12500.00", "150000.00", "1257L", period=12)

    assert facts.tax_code.cumulative is True
    with pytest.raises(UnsupportedPayslip):
        income_tax_due(facts)


def test_taper_guard_applies_on_the_non_cumulative_path():
    """The other half. non_cumulative_income_tax_due() returned £2,290.50
    for this case with no refusal at all before the fix - it is reached by
    dispatch from cumulative_income_tax_due(), so a guard placed only on
    the cumulative branch would have missed it."""
    facts = _facts("12500.00", "150000.00", "1257L M1", period=12)

    assert facts.tax_code.cumulative is False
    with pytest.raises(UnsupportedPayslip):
        income_tax_due(facts)


def test_taper_guard_uses_annualised_pay_not_year_to_date():
    """Basis check. At month 3 a £150,000 earner is only £37,500 in, so a
    year-to-date test would let them through for most of the tax year -
    exactly the wrong-figure window this guard closes."""
    facts = _facts("12500.00", "37500.00", "1257L", period=3)

    assert facts.gross_ytd < Decimal("100000")  # YTD alone would allow it
    with pytest.raises(UnsupportedPayslip):
        income_tax_due(facts)


def test_taper_guard_does_not_refuse_a_zero_allowance_code():
    """BR, D0, D1 and 0T grant no allowance, so there is nothing to taper
    and the banded arithmetic is already correct at any income. Refusing
    them would refuse a calculation the engine gets right."""
    for code in ("BR", "D0", "D1", "0T"):
        facts = _facts("12500.00", "150000.00", code, period=12)
        assert income_tax_due(facts) > Decimal("0"), code


def test_zero_allowance_code_is_correct_at_high_income():
    """The claim the previous test rests on, checked rather than asserted.
    0T on £150,000: 20% of 37,700 + 40% of 87,440 + 45% of 24,860."""
    facts = _facts("150000.00", "150000.00", "0T", period=12)

    assert income_tax_due(facts) == Decimal("53703.00")


def test_nt_is_answered_not_refused_at_high_income():
    """NT is exempt outright, so the allowance is irrelevant and a high
    earner on NT must get an answer rather than a refusal."""
    facts = _facts("12500.00", "150000.00", "NT", period=12)

    assert income_tax_due(facts) == Decimal("0")


def test_the_taper_guard_is_reachable_from_income_tax_due():
    """FR-04's actual defect was not a missing check - it was a check on a
    function nothing called. This asserts reachability from the live entry
    point, so the guard cannot drift back onto a dead path.

    calculate_pay_breakdown() is what analysis.analyse_payslip() calls, and
    it reaches the guard only via income_tax_due().
    """
    facts = _facts("12500.00", "150000.00", "1257L", period=12)

    with pytest.raises(UnsupportedPayslip):
        calculations.income_tax_due(facts)

    with pytest.raises(UnsupportedPayslip):
        calculations.calculate_pay_breakdown(facts)


def test_the_dead_annual_tax_functions_are_gone():
    """The other half of FR-04: a live guard and a dead guard must not sit
    side by side. annual_income_tax() held the only £100k refusal in the
    file and had zero callers; taxable_income() was called only by it; and
    personal_allowance_for_income() computed a tapered allowance the engine
    has no business computing while it refuses the taper.

    If any of these comes back, the duplicate-guard hazard comes back with
    it.
    """
    for name in (
        "annual_income_tax",
        "taxable_income",
        "personal_allowance_for_income",
    ):
        assert not hasattr(calculations, name), (
            f"{name}() is back - see FR-04. If it is genuinely needed again, "
            f"make sure it does not reintroduce a second £100k guard."
        )
