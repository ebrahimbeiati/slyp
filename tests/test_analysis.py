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
from slyp.analysis import _facts_from_extract, analyse_payslip
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


@pytest.fixture
def enforcing(monkeypatch):
    """The guard is switched off for the demo (see
    calculations.ENFORCE_SUPPORTED_TAX_YEAR). These tests cover the
    enforcing behaviour so it's still verified when it goes back on."""
    monkeypatch.setattr(calculations, "ENFORCE_SUPPORTED_TAX_YEAR", True)


def test_analyse_payslip_proceeds_for_the_supported_tax_year(enforcing):
    extract = _extract(tax_year="2026/27")
    result = analyse_payslip(extract)
    assert result.status == "ok"


def test_analyse_payslip_refuses_a_prior_tax_year(enforcing):
    extract = _extract(tax_year="2025/26")
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert "2025/26" in result.failure_reason
    assert result.findings == []
    assert result.score is None


def test_analyse_payslip_refuses_when_tax_year_is_undeterminable(enforcing):
    extract = _extract(tax_year=None)
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert "could not be determined" in result.failure_reason
    assert result.findings == []
    assert result.score is None


# The demo state: a prior-year payslip must actually analyse rather than
# be refused. Delete when the guard goes back on.
@pytest.mark.parametrize("tax_year", ["2025/26", None])
def test_analyse_payslip_proceeds_for_a_prior_year_while_the_guard_is_off(
    monkeypatch, tax_year
):
    monkeypatch.setattr(calculations, "ENFORCE_SUPPORTED_TAX_YEAR", False)
    result = analyse_payslip(_extract(tax_year=tax_year))
    assert result.status == "ok"
