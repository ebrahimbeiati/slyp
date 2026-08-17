"""
Tests for the findings layer.

Fixtures are built by hand to match five real payslip shapes referenced in
the phase 4 brief (0T M1, 1257L monthly, 1257L W1 weekly), plus a couple of
purpose-built ones for the negative cases. `income_tax_due`, `annualise`
and `student_loan_due` are stubs at the time this file is written - most
tests exercise the pipeline as it behaves with them unimplemented, and a
couple mock them to prove the wiring that will light up once Ayaan's work
lands.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from slyp.contract import (
    Deductions,
    Pay,
    Period,
    PayslipExtract,
    Source,
    TaxCodeRead,
    UserContext,
)
from slyp.findings import (
    _check_national_insurance,
    _check_no_allowance,
    _check_pension,
    _check_reconciliation,
    _clear_findings,
    _order_and_cap,
    analyse,
    can_run,
    gate_report,
)
from slyp.calculations import parse_tax_code


# --------------------------------------------------------------------------
# Fixture builder
# --------------------------------------------------------------------------


def _extract(
    *,
    tax_code="1257L",
    frequency="monthly",
    period_number=1,
    gross_this_period="800.00",
    gross_ytd="800.00",
    income_tax="0.00",
    income_tax_ytd="0.00",
    national_insurance="0.00",
    national_insurance_ytd="0.00",
    ni_category="A",
    pension_employee="40.00",
    pension_employer="60.00",
    student_loan=None,
    student_loan_plan=None,
    net_pay=None,
    unreadable_fields=None,
    confidence=None,
    reconciles=None,
) -> PayslipExtract:
    """
    Defaults to a clean 1257L monthly payslip on a low, untaxed income -
    the "everything's fine" case. Override individual fields per test.
    """
    deductions_kwargs = dict(
        income_tax=Decimal(income_tax) if income_tax is not None else None,
        income_tax_ytd=Decimal(income_tax_ytd) if income_tax_ytd is not None else None,
        national_insurance=Decimal(national_insurance) if national_insurance is not None else None,
        national_insurance_ytd=Decimal(national_insurance_ytd)
        if national_insurance_ytd is not None
        else None,
        ni_category=ni_category,
        pension_employee=Decimal(pension_employee) if pension_employee is not None else None,
        pension_employer=Decimal(pension_employer) if pension_employer is not None else None,
        student_loan=Decimal(student_loan) if student_loan is not None else None,
        student_loan_plan=student_loan_plan,
    )

    if net_pay is None:
        gross_dec = Decimal(gross_this_period)
        total_deductions = sum(
            v for v in (
                deductions_kwargs["income_tax"],
                deductions_kwargs["national_insurance"],
                deductions_kwargs["pension_employee"],
                deductions_kwargs["student_loan"],
            ) if v is not None
        ) or Decimal("0")
        net_pay = gross_dec - total_deductions
    else:
        net_pay = Decimal(net_pay)

    extract = PayslipExtract(
        source=Source(filename="test.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        employer_name=None,
        period=Period(
            pay_date=None,
            period_number=period_number,
            frequency=frequency,
            tax_year="2026/27",
        ),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(
            hourly_rate=None,
            hours=None,
            gross_this_period=Decimal(gross_this_period),
            gross_ytd=Decimal(gross_ytd),
        ),
        deductions=Deductions(**deductions_kwargs),
        net_pay=net_pay,
        confidence=confidence or {},
        unreadable_fields=unreadable_fields or [],
        warnings=[],
        reconciles=reconciles,
    )
    return extract


def _reconciling(extract: PayslipExtract) -> PayslipExtract:
    """Recompute net_pay so `reconciles` comes out True, and set it."""
    total = sum(
        v
        for v in (
            extract.deductions.income_tax,
            extract.deductions.national_insurance,
            extract.deductions.pension_employee,
            extract.deductions.student_loan,
        )
        if v is not None
    ) or Decimal("0")
    return extract.model_copy(
        update={"net_pay": extract.pay.gross_this_period - total, "reconciles": True}
    )


# --------------------------------------------------------------------------
# The three payslips named in the brief
# --------------------------------------------------------------------------


def _zero_t_m1_payslip(**overrides) -> PayslipExtract:
    defaults = dict(
        tax_code="0T M1",
        frequency="monthly",
        period_number=9,
        gross_this_period="123.00",
        gross_ytd="123.00",
        income_tax="24.60",
        income_tax_ytd="24.60",
        national_insurance="0.00",
        pension_employee=None,
        pension_employer=None,
    )
    defaults.update(overrides)
    return _reconciling(_extract(**defaults))


def _1257l_monthly_payslip(**overrides) -> PayslipExtract:
    defaults = dict(
        tax_code="1257L",
        frequency="monthly",
        period_number=1,
        gross_this_period="800.00",
        gross_ytd="800.00",
        income_tax="0.00",
        income_tax_ytd="0.00",
        national_insurance="0.00",
    )
    defaults.update(overrides)
    extract = _extract(**defaults)
    if "net_pay" not in overrides and "reconciles" not in overrides:
        extract = _reconciling(extract)
    return extract


def _1257l_w1_weekly_payslip(**overrides) -> PayslipExtract:
    defaults = dict(
        tax_code="1257L W1",
        frequency="weekly",
        period_number=10,
        gross_this_period="300.00",
        gross_ytd="3000.00",
        income_tax="20.00",
        income_tax_ytd="300.00",
        national_insurance="4.64",  # (300 - 242) * 0.08, see calculations.RATES
    )
    defaults.update(overrides)
    return _reconciling(_extract(**defaults))


# --------------------------------------------------------------------------
# can_run — the confidence gate
# --------------------------------------------------------------------------


def test_can_run_true_when_fields_present_and_confident():
    extract = _1257l_monthly_payslip()
    assert can_run(extract, ["tax_code.value", "pay.gross_this_period"]) is True


def test_can_run_false_when_field_is_none():
    extract = _1257l_monthly_payslip(student_loan=None)
    assert can_run(extract, ["deductions.student_loan"]) is False


def test_can_run_false_when_field_in_unreadable_fields():
    extract = _1257l_monthly_payslip(unreadable_fields=["tax_code.value"])
    assert can_run(extract, ["tax_code.value"]) is False


def test_can_run_false_when_confidence_below_threshold():
    extract = _1257l_monthly_payslip(confidence={"tax_code.value": 0.3})
    assert can_run(extract, ["tax_code.value"]) is False


def test_can_run_true_when_confidence_at_or_above_threshold():
    extract = _1257l_monthly_payslip(confidence={"tax_code.value": 0.7})
    assert can_run(extract, ["tax_code.value"]) is True


# --------------------------------------------------------------------------
# 0T M1 — must fire both R2 (emergency basis) and R3 (no allowance)
# --------------------------------------------------------------------------


def test_zero_t_m1_fires_emergency_basis_and_no_allowance():
    extract = _zero_t_m1_payslip()
    result = analyse([extract])

    ids = {f.id for f in result.findings}
    assert "tax_code_emergency_basis" in ids
    assert "tax_code_no_allowance" in ids
    assert "tax_code_unreadable" not in ids
    assert "tax_code_unparseable" not in ids


def test_zero_t_m1_no_allowance_is_action_when_only_job_true():
    extract = _zero_t_m1_payslip()
    result = analyse([extract], context=UserContext(only_job=True))

    no_allowance = next(f for f in result.findings if f.id == "tax_code_no_allowance")
    assert no_allowance.severity == "action"


def test_zero_t_m1_no_allowance_is_advisory_and_conditional_when_only_job_unanswered():
    extract = _zero_t_m1_payslip()
    result = analyse([extract], context=UserContext(only_job=None))

    no_allowance = next(f for f in result.findings if f.id == "tax_code_no_allowance")
    assert no_allowance.severity == "advisory"
    assert "if" in no_allowance.explanation.lower()


def test_zero_t_m1_no_allowance_never_claims_overpayment_when_only_job_false():
    extract = _zero_t_m1_payslip()
    result = analyse([extract], context=UserContext(only_job=False))

    no_allowance = next(f for f in result.findings if f.id == "tax_code_no_allowance")
    assert "overpayment" not in no_allowance.explanation.lower()
    assert no_allowance.estimate is None


# --------------------------------------------------------------------------
# 1257L monthly — clean payslip: clears, no actions
# --------------------------------------------------------------------------


def test_1257l_monthly_produces_clears_and_no_actions():
    extract = _1257l_monthly_payslip()
    result = analyse([extract])

    assert all(f.severity != "action" for f in result.findings)
    clear_ids = {f.id for f in result.findings if f.severity == "clear"}
    assert "tax_code_looks_right" in clear_ids
    assert "figures_reconcile" in clear_ids
    assert result.verdict.severity == "clear"
    assert result.verdict.headline == "This payslip looks fine to us"


# --------------------------------------------------------------------------
# 1257L W1 weekly — R2 but not R3
# --------------------------------------------------------------------------


def test_1257l_w1_weekly_fires_emergency_basis_but_not_no_allowance():
    extract = _1257l_w1_weekly_payslip()
    result = analyse([extract])

    ids = {f.id for f in result.findings}
    assert "tax_code_emergency_basis" in ids
    assert "tax_code_no_allowance" not in ids


# --------------------------------------------------------------------------
# Negative tests
# --------------------------------------------------------------------------


def test_rule_produces_nothing_when_its_source_field_is_unreadable():
    extract = _1257l_monthly_payslip(unreadable_fields=["deductions.pension_employee"])
    # pension_employee value is still 40.00 on the object, but it's listed
    # as unreadable - the pension check must not trust it either way.
    result = _check_pension(extract)
    assert result.outcome == "gated"
    assert result.finding is None


def test_no_finding_carries_an_estimate_while_a_calculation_is_a_stub():
    # income_tax_due, annualise and student_loan_due are all real stubs at
    # the time this test runs (unmocked) - every estimate that depends on
    # one of them must be absent, not wrong.
    extract = _zero_t_m1_payslip()
    result = analyse([extract])

    for finding in result.findings:
        assert finding.estimate is None
    assert result.projections == []


# --------------------------------------------------------------------------
# Whole pipeline against stub calculations
# --------------------------------------------------------------------------


def test_pipeline_produces_sensible_findings_with_stub_calculations():
    extract = _zero_t_m1_payslip()
    result = analyse([extract], context=UserContext(only_job=True))

    assert result.status == "ok"
    assert result.score is not None
    assert result.score.value < 100
    assert result.verdict.severity == "action"
    # R4 needs annualise(), a stub - it must not fire, not error.
    assert not any(f.id == "under_personal_allowance_but_taxed" for f in result.findings)


# --------------------------------------------------------------------------
# Whole pipeline once the stub calculations are mocked
# --------------------------------------------------------------------------


def test_pipeline_produces_estimates_once_calculations_are_mocked():
    extract = _zero_t_m1_payslip()

    with patch("slyp.findings.income_tax_due", return_value=Decimal("2.00")), patch(
        "slyp.findings.annualise", return_value=Decimal("5000.00")
    ):
        result = analyse([extract], context=UserContext(only_job=True))

    emergency = next(f for f in result.findings if f.id == "tax_code_emergency_basis")
    assert emergency.estimate is not None
    assert emergency.estimate.amount_gbp == Decimal("6.60")  # 24.60 - (9 * 2.00)

    under_allowance = next(
        f for f in result.findings if f.id == "under_personal_allowance_but_taxed"
    )
    assert under_allowance.estimate.amount_gbp == Decimal("24.60")

    assert len(result.projections) == 1
    projection = result.projections[0]
    assert projection.key == "emergency_code_full_year"
    assert len(projection.points) >= 2


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


def test_reconciliation_failure_produces_advisory_finding_with_difference():
    extract = _1257l_monthly_payslip(net_pay="700.00", reconciles=False)
    result = _check_reconciliation(extract)

    assert result.outcome == "failed"
    assert result.finding.severity == "advisory"
    assert "60.00" in result.finding.explanation  # 800 - 40 (pension) - 700 net = 60 gap


def test_reconciliation_unknown_is_gated_not_passed():
    extract = _1257l_monthly_payslip(reconciles=None)
    result = _check_reconciliation(extract)
    assert result.outcome == "gated"


# --------------------------------------------------------------------------
# Ordering and capping
# --------------------------------------------------------------------------


def test_order_and_cap_puts_action_before_advisory_before_clear():
    extract = _zero_t_m1_payslip()
    result = analyse([extract], context=UserContext(only_job=True))

    severities = [f.severity for f in result.findings]
    assert severities == sorted(severities, key={"action": 0, "advisory": 1, "clear": 2}.get)


def test_clear_findings_capped_at_three():
    extract = _1257l_monthly_payslip()
    clears = _clear_findings(extract, tax_code=None, r2_fired=False, r3_fired=False)
    assert len(clears) <= 3


# --------------------------------------------------------------------------
# Empty input
# --------------------------------------------------------------------------


def test_analyse_with_no_extracts_fails_loudly():
    result = analyse([])
    assert result.status == "unreadable"
    assert result.failure_reason is not None


def test_analyse_with_multiple_extracts_warns_and_uses_the_first():
    first = _1257l_monthly_payslip()
    second = _zero_t_m1_payslip()
    result = analyse([first, second])

    assert result.extract.period.frequency == first.period.frequency
    assert any("first" in w.lower() for w in result.extract.warnings)


# --------------------------------------------------------------------------
# Phase 4.1 item 4 — the 0T sentence must not appear in the only_job=False
# branch, but must still appear when only_job is True or unanswered.
# --------------------------------------------------------------------------


def test_zero_t_only_job_false_does_not_mention_0t_or_undercut_the_reassurance():
    extract = _zero_t_m1_payslip()
    tax_code = parse_tax_code("0T")
    result = _check_no_allowance(extract, tax_code, UserContext(only_job=False))

    assert "0T" not in result.finding.explanation
    assert "genuinely wrong" not in result.finding.explanation
    assert result.finding.explanation.endswith("worth checking that it actually is.")


def test_zero_t_only_job_true_still_mentions_the_0t_caveat():
    extract = _zero_t_m1_payslip()
    tax_code = parse_tax_code("0T")
    result = _check_no_allowance(extract, tax_code, UserContext(only_job=True))

    assert "0T" in result.finding.explanation
    assert "genuinely wrong" in result.finding.explanation


def test_zero_t_only_job_unanswered_still_mentions_the_0t_caveat():
    extract = _zero_t_m1_payslip()
    tax_code = parse_tax_code("0T")
    result = _check_no_allowance(extract, tax_code, UserContext(only_job=None))

    assert "0T" in result.finding.explanation
    assert "genuinely wrong" in result.finding.explanation


def test_br_only_job_false_has_no_0t_sentence_either():
    """BR isn't 0T, so it only ever had the generic second-job sentence -
    confirms the False-branch fix applies regardless of tax code kind."""
    extract = _1257l_monthly_payslip(tax_code="BR")
    tax_code = parse_tax_code("BR")
    result = _check_no_allowance(extract, tax_code, UserContext(only_job=False))

    assert result.finding.explanation.endswith("worth checking that it actually is.")


# --------------------------------------------------------------------------
# Phase 4.1 item 5 — emergency-basis explanation when this period's tax is
# genuinely zero (one period's allowance covered this period's pay).
# --------------------------------------------------------------------------


def test_emergency_basis_zero_tax_this_period_says_it_has_not_cost_anything():
    extract = _1257l_w1_weekly_payslip(income_tax="0.00")
    result = analyse([extract])

    emergency = next(f for f in result.findings if f.id == "tax_code_emergency_basis")
    assert "hasn't cost you anything" in emergency.explanation
    assert "busier" in emergency.explanation


def test_emergency_basis_nonzero_tax_this_period_uses_the_standard_wording():
    extract = _1257l_w1_weekly_payslip(income_tax="20.00")
    result = analyse([extract])

    emergency = next(f for f in result.findings if f.id == "tax_code_emergency_basis")
    assert "hasn't cost you anything" not in emergency.explanation
    assert "starter checklist" in emergency.explanation


def test_emergency_basis_unreadable_period_tax_uses_the_standard_wording():
    """An unreadable income_tax must not be treated as a confirmed zero -
    the cautious default is the standard (cost-implying) wording."""
    extract = _1257l_w1_weekly_payslip(unreadable_fields=["deductions.income_tax"])
    result = analyse([extract])

    emergency = next(f for f in result.findings if f.id == "tax_code_emergency_basis")
    assert "hasn't cost you anything" not in emergency.explanation


# --------------------------------------------------------------------------
# Phase 4.1 items 1 & 3 — National Insurance is now its own gated check,
# with a minimal field list and a visible reason when gated.
# --------------------------------------------------------------------------


def test_ni_check_requires_only_gross_ni_and_frequency():
    # No YTD figures, no ni_category - see _check_national_insurance's
    # docstring for why neither belongs in the gate.
    extract = _1257l_monthly_payslip(
        gross_this_period="800.00", national_insurance="0.00", ni_category=None
    )
    result = _check_national_insurance(extract)
    assert result.outcome == "passed"
    assert result.finding.id == "ni_looks_right"


def test_ni_check_gated_when_frequency_unreadable_and_visible_in_gate_report():
    extract = _1257l_monthly_payslip(unreadable_fields=["period.frequency"])
    result = _check_national_insurance(extract)

    assert result.outcome == "gated"
    assert result.note is not None
    assert "National Insurance" in result.note
    assert "pay frequency" in result.note

    report = gate_report(extract)
    ni_entry = next(e for e in report if e["id"] == "national_insurance")
    assert ni_entry["outcome"] == "gated"
    assert "pay frequency" in ni_entry["note"]


def test_ni_check_gated_does_not_count_as_passed_in_the_score():
    extract = _1257l_monthly_payslip(unreadable_fields=["period.frequency"])
    result = analyse([extract])

    # tax_code_readable, tax_code_emergency_basis, tax_code_no_allowance,
    # reconciliation and pension all still run - only NI is gated.
    assert result.score.checks_run == 5
    ni_findings = [f for f in result.findings if f.id == "ni_looks_right"]
    assert ni_findings == []


def test_ni_mismatch_produces_no_finding_but_does_not_count_as_passed():
    extract = _1257l_monthly_payslip(national_insurance="999.00")
    result = _check_national_insurance(extract)

    assert result.outcome == "failed"
    assert result.finding is None


# --------------------------------------------------------------------------
# gate_report()
# --------------------------------------------------------------------------


def test_gate_report_lists_every_check_with_an_outcome():
    extract = _1257l_monthly_payslip()
    report = gate_report(extract)

    ids = {entry["id"] for entry in report}
    assert {
        "tax_code_readable",
        "tax_code_emergency_basis",
        "tax_code_no_allowance",
        "under_personal_allowance_but_taxed",
        "reconciliation",
        "pension",
        "national_insurance",
    }.issubset(ids)
    for entry in report:
        assert entry["outcome"] in {"gated", "passed", "failed"}


def test_gate_report_stops_at_tax_code_rules_when_tax_code_is_unreadable():
    extract = _1257l_monthly_payslip(unreadable_fields=["tax_code.value"])
    report = gate_report(extract)

    ids = {entry["id"] for entry in report}
    assert "tax_code_readable" in ids
    assert "tax_code_emergency_basis" not in ids
    assert "tax_code_no_allowance" not in ids
