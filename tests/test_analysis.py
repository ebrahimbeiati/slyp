"""
Tests for slyp.analysis internals - specifically _facts_from_extract()'s
handling of unreadable_fields (as distinct from None-ness).

extract_payslip() already nulls every field it flags unreadable before
returning a PayslipExtract, so these two checks agree for data that came
through the real pipeline. analyse_payslip() is a public function
callable with any hand-built PayslipExtract though (as every test in this
suite does), and nothing in the contract enforces that a field can't be
present while also listed as unreadable - so _facts_from_extract() has to
check both explicitly, the same way findings.py's _check_* functions do.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from slyp import calculations
from slyp.analysis import _facts_from_extract, analyse_payslip, build_score
from slyp.findings import CalculationComparison
from slyp.calculations import parse_tax_code
from slyp.contract import (
    Deductions,
    Pay,
    Period,
    PayslipExtract,
    Source,
    TaxCodeRead,
)

TAX_CODE = parse_tax_code("1257L")


def _extract(*, unreadable_fields=None, ni_category="A", student_loan_plan=None, tax_year="2026/27"):
    return PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=1, frequency="monthly", tax_year=tax_year),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=Decimal("800.00"), gross_ytd=Decimal("800.00")),
        deductions=Deductions(
            income_tax=Decimal("0.00"),
            national_insurance=Decimal("0.00"),
            ni_category=ni_category,
            student_loan_plan=student_loan_plan,
        ),
        net_pay=Decimal("800.00"),
        unreadable_fields=unreadable_fields or [],
    )


# --------------------------------------------------------------------------
# Happy path - regression
# --------------------------------------------------------------------------


def test_facts_from_extract_builds_normally_with_nothing_unreadable():
    extract = _extract()
    facts = _facts_from_extract(extract, TAX_CODE)
    assert facts.frequency == "monthly"
    assert facts.period_number == 1
    assert facts.gross_ytd == Decimal("800.00")
    assert facts.ni_category == "A"
    assert facts.student_loan_plan is None


# --------------------------------------------------------------------------
# Unreadable (present-but-untrusted) must refuse, not just None
# --------------------------------------------------------------------------


def test_facts_from_extract_refuses_unreadable_frequency():
    extract = _extract(unreadable_fields=["period.frequency"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_period_number():
    extract = _extract(unreadable_fields=["period.period_number"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_gross_this_period():
    extract = _extract(unreadable_fields=["pay.gross_this_period"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_gross_ytd():
    extract = _extract(unreadable_fields=["pay.gross_ytd"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_ni_category():
    # A category is present ("A") but not confidently read - must refuse
    # rather than silently trust the guess.
    extract = _extract(unreadable_fields=["deductions.ni_category"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_student_loan_plan():
    # A plan is present ("2") but not confidently read - must refuse
    # rather than silently pick that plan or silently treat it as no
    # loan at all.
    extract = _extract(unreadable_fields=["deductions.student_loan_plan"], student_loan_plan="2")
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


# --------------------------------------------------------------------------
# None (genuinely absent) must keep its existing, legitimate default -
# these are NOT the same as unreadable and must not start refusing too
# --------------------------------------------------------------------------


def test_facts_from_extract_defaults_absent_ni_category_to_a():
    extract = _extract(ni_category=None)
    facts = _facts_from_extract(extract, TAX_CODE)
    assert facts.ni_category == "A"


def test_facts_from_extract_defaults_absent_student_loan_plan_to_none():
    extract = _extract(student_loan_plan=None)
    facts = _facts_from_extract(extract, TAX_CODE)
    assert facts.student_loan_plan is None


# --------------------------------------------------------------------------
# End to end: analyse_payslip() degrades gracefully rather than crashing
# or computing on untrusted data
# --------------------------------------------------------------------------


def test_analyse_payslip_degrades_gracefully_when_frequency_unreadable():
    extract = _extract(unreadable_fields=["period.frequency"])
    result = analyse_payslip(extract)
    assert result.status == "ok"
    assert any(f.id == "calculation_unavailable" for f in result.findings)
    assert not any(f.id == "income_tax_differs_from_calculation" for f in result.findings)


def test_analyse_payslip_degrades_gracefully_when_ni_category_unreadable():
    extract = _extract(unreadable_fields=["deductions.ni_category"])
    result = analyse_payslip(extract)
    assert result.status == "ok"
    assert any(f.id == "calculation_unavailable" for f in result.findings)
    assert not any(f.id == "national_insurance_differs_from_calculation" for f in result.findings)


# --------------------------------------------------------------------------
# Tax year gate - a payslip must not be calculated with the wrong year's
# rates, and an undeterminable tax year must refuse rather than assume
# the current one.
# --------------------------------------------------------------------------


def test_analyse_payslip_proceeds_for_the_supported_tax_year():
    extract = _extract(tax_year="2026/27")
    result = analyse_payslip(extract)
    assert result.status == "ok"


def test_analyse_payslip_refuses_a_prior_tax_year():
    extract = _extract(tax_year="2025/26")
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert "2025/26" in result.failure_reason
    assert result.findings == []
    assert result.score is None


def test_analyse_payslip_refuses_when_tax_year_is_undeterminable():
    extract = _extract(tax_year=None)
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert "could not be determined" in result.failure_reason
    assert result.findings == []
    assert result.score is None


def test_the_refusal_names_the_tax_year_as_the_reason():
    """
    Distinct status and a message naming the real reason - not "this tax
    code needs a manual check" or a generic unreadable error, which would
    send the user to check the wrong thing.
    """
    result = analyse_payslip(_extract(tax_year="2025/26"))

    assert result.status == "unsupported"
    assert "2025/26" in result.failure_reason
    assert "not currently supported" in result.failure_reason
    assert result.verdict.headline == (
        "This payslip is from a tax year we don't yet support"
    )


# --------------------------------------------------------------------------
# Score: a check with nothing to check is not a pass
# --------------------------------------------------------------------------


def _scored(
    *,
    gross,
    tax,
    ni,
    net,
    gross_ytd=None,
    tax_code="1257L",
    period_number=1,
    unreadable_fields=None,
):
    extract = PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(
            period_number=period_number, frequency="monthly", tax_year="2026/27"
        ),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(
            gross_this_period=Decimal(gross),
            gross_ytd=Decimal(gross_ytd or gross),
        ),
        deductions=Deductions(
            income_tax=Decimal(tax) if tax is not None else None,
            income_tax_ytd=Decimal(tax) if tax is not None else None,
            national_insurance=Decimal(ni) if ni is not None else None,
            ni_category="A",
        ),
        net_pay=Decimal(net),
        unreadable_fields=unreadable_fields or [],
    )
    return analyse_payslip(extract).score


def test_under_every_threshold_the_zero_comparisons_do_not_count_as_passes():
    """
    The £583.55 payslip. Income tax and NI are both £0.00 due and £0.00
    deducted - nothing could have been wrong, so nothing was verified.
    Those two must not be counted as passes.
    """
    score = _scored(gross="583.55", gross_ytd="854.07", tax="0.00", ni="0.00", net="583.55")

    assert score.checks_run == 2
    assert len(score.not_applicable) == 2
    assert any("income tax" in reason.lower() for reason in score.not_applicable)
    assert any("national insurance" in reason.lower() for reason in score.not_applicable)


def test_above_the_thresholds_every_check_genuinely_runs():
    score = _scored(
        gross="2500.00",
        gross_ytd="7500.00",
        tax="290.50",
        ni="116.16",
        net="2093.34",
        tax_code="1257L M1",
        period_number=5,
    )

    assert score.checks_run == 4
    assert score.checks_passed == 4
    assert score.not_applicable == []
    assert score.value == 100


def test_a_calculation_that_never_ran_is_not_four_silent_passes():
    """
    The case from the reported screenshot: the engine could not calculate
    (no period number), so no tax or NI finding could possibly fire - and
    the absence of a finding used to be counted as a pass, producing
    "4/4 checks clear" beside "we could not complete every calculation".
    """
    score = _scored(
        gross="2500.00",
        gross_ytd="7500.00",
        tax="290.50",
        ni="116.16",
        net="2093.34",
        unreadable_fields=["period.period_number"],
    )

    assert score.checks_run == 2  # reconciliation and tax code only
    assert len(score.not_applicable) == 2
    assert all("couldn't work out" in reason for reason in score.not_applicable)


def test_no_applicable_check_scores_none_rather_than_zero():
    """
    A zero would read as a failing payslip. None means unscored, which is
    what "we could not check anything here" actually is.

    Exercised through build_score() directly rather than analyse_payslip():
    an unreadable tax code fails validate_extract() and stops the analysis
    before scoring, so the tax-code check always runs on any result that
    reaches a score. The guard still has to hold for direct callers, and
    for the day validate_extract() softens.
    """
    extract = PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=1, frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=Decimal("583.55"), gross_ytd=Decimal("583.55")),
        deductions=Deductions(income_tax=None, national_insurance=None, ni_category="A"),
        net_pay=Decimal("583.55"),
        unreadable_fields=["tax_code.value"],
    )

    score = build_score(findings=[], extract=extract, comparison=CalculationComparison())

    assert score.checks_run == 0
    assert score.checks_passed == 0
    assert score.value is None
    assert len(score.not_applicable) == 4


def test_score_without_a_comparison_treats_every_calculated_check_as_not_run():
    """
    build_score()'s comparison argument defaults to None for backwards
    compatibility. That must mean "nothing was calculated", not "the
    calculation agreed" - the difference between a hedge and a pass.
    """
    extract = PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=1, frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=Decimal("2500.00"), gross_ytd=Decimal("2500.00")),
        deductions=Deductions(
            income_tax=Decimal("290.50"),
            national_insurance=Decimal("116.16"),
            ni_category="A",
        ),
        net_pay=Decimal("2093.34"),
    )

    score = build_score(findings=[], extract=extract)

    assert score.checks_run == 2  # reconciliation + tax code
    assert len(score.not_applicable) == 2
