"""
The same expectations verify/run_regression.py enforces end-to-end, pinned
at the analysis layer with no model call.

Two layers on purpose. This file catches a logic regression in seconds -
scoring rules, the estimate's branches, BR's three-way split. It cannot
catch an extraction regression, because it builds the PayslipExtract
directly instead of reading the PDF; a redaction change that eats a
needed line, or a model that stops reading a label, only shows up in
verify/run_regression.py. Run that before the demo; run this on every
change.

The figures here are the ones printed on the fixture PDFs in
verify/fixtures/ - keep them in step.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from slyp.analysis import analyse_payslip
from slyp.contract import (
    Deductions,
    Pay,
    Period,
    PayslipExtract,
    Source,
    TaxCodeRead,
    UserContext,
)


def _extract(
    *,
    tax_code,
    gross,
    tax,
    ni,
    net,
    gross_ytd,
    tax_ytd,
    pension=None,
    period_number=5,
):
    return PayslipExtract(
        source=Source(filename="f.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(
            period_number=period_number, frequency="monthly", tax_year="2026/27"
        ),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(gross_this_period=Decimal(gross), gross_ytd=Decimal(gross_ytd)),
        deductions=Deductions(
            income_tax=Decimal(tax),
            income_tax_ytd=Decimal(tax_ytd),
            national_insurance=Decimal(ni),
            ni_category="A",
            pension_employee=Decimal(pension) if pension is not None else None,
        ),
        net_pay=Decimal(net),
    )


def _br_second_job():
    """verify/fixtures/br_second_job.pdf"""
    return _extract(
        tax_code="BR",
        gross="476.00",
        tax="95.20",
        ni="0.00",
        net="380.80",
        gross_ytd="2380.00",
        tax_ytd="476.00",
    )


def _under_all_thresholds():
    """verify/fixtures/under_all_thresholds.pdf"""
    return _extract(
        tax_code="1257L",
        gross="583.55",
        tax="0.00",
        ni="0.00",
        net="583.55",
        gross_ytd="854.07",
        tax_ytd="0.00",
    )


def _emergency_midyear_start():
    """verify/fixtures/emergency_m1_midyear_start.pdf"""
    return _extract(
        tax_code="1257L M1",
        gross="2500.00",
        tax="290.50",
        ni="116.16",
        net="1968.34",
        gross_ytd="7500.00",
        tax_ytd="871.50",
        pension="125.00",
    )


def _emergency_level_pay():
    """verify/fixtures/emergency_m1_level_pay.pdf"""
    return _extract(
        tax_code="1257L M1",
        gross="2500.00",
        tax="290.50",
        ni="116.16",
        net="1968.34",
        gross_ytd="12500.00",
        tax_ytd="1452.50",
        pension="125.00",
    )


def _estimate(result):
    return next((f.estimate for f in result.findings if f.estimate is not None), None)


# --------------------------------------------------------------------------
# BR on a second job
# --------------------------------------------------------------------------


def test_br_second_job_is_clear_and_claims_nothing():
    result = analyse_payslip(_br_second_job(), UserContext(only_job=False))

    assert result.status == "ok"
    assert any(f.id == "tax_code_br_multiple_jobs" for f in result.findings)
    assert _estimate(result) is None


def test_br_second_job_reports_ni_as_not_applicable_not_passed():
    """£476/month is under the primary threshold, so the NI check compares
    £0.00 with £0.00 and establishes nothing."""
    score = analyse_payslip(_br_second_job(), UserContext(only_job=False)).score

    assert (score.checks_passed, score.checks_run) == (3, 3)
    assert any("National Insurance" in reason for reason in score.not_applicable)


# --------------------------------------------------------------------------
# Under every threshold
# --------------------------------------------------------------------------


def test_under_all_thresholds_reports_two_of_two_with_both_reasons():
    """The original case: this used to report 4/4 having verified nothing.
    Reconciliation and the tax-code check genuinely run; income tax and NI
    do not."""
    score = analyse_payslip(_under_all_thresholds(), UserContext(only_job=True)).score

    assert (score.checks_passed, score.checks_run) == (2, 2)
    assert len(score.not_applicable) == 2
    assert any("income tax" in reason.lower() for reason in score.not_applicable)
    assert any("National Insurance" in reason for reason in score.not_applicable)


# --------------------------------------------------------------------------
# Emergency code - the demo's headline figure
# --------------------------------------------------------------------------


def test_emergency_estimate_is_stated_when_it_is_the_only_job():
    result = analyse_payslip(_emergency_midyear_start(), UserContext(only_job=True))
    estimate = _estimate(result)

    assert estimate is not None
    assert estimate.amount_gbp == Decimal("419.00")
    assert "if" not in estimate.label.lower()


def test_emergency_estimate_is_conditional_when_not_told():
    result = analyse_payslip(_emergency_midyear_start(), UserContext(only_job=None))
    estimate = _estimate(result)

    assert estimate is not None
    assert estimate.amount_gbp == Decimal("419.00")
    assert "only employment this tax year" in estimate.label


def test_emergency_estimate_is_withheld_for_a_second_job():
    result = analyse_payslip(_emergency_midyear_start(), UserContext(only_job=False))

    assert _estimate(result) is None


@pytest.mark.parametrize("only_job", [True, None, False])
def test_level_pay_on_m1_never_shows_a_figure_in_any_branch(only_job):
    """M1 with level pay all year costs exactly nothing - one month's
    allowance for each month paid equals the cumulative allowance for each
    month elapsed. No branch may invent a figure here."""
    result = analyse_payslip(_emergency_level_pay(), UserContext(only_job=only_job))

    assert _estimate(result) is None
    assert any(f.id == "tax_code_emergency_basis" for f in result.findings)
