"""
Tests for the findings layer (slyp.findings) and its wiring into
slyp.analysis.analyse_payslip().

Fixtures build PayslipExtract objects directly and, where a finding needs a
CalculationComparison, either build one by hand or run the real engine via
calculate_from_values() so the arithmetic is genuine rather than mocked.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from slyp.calculations import calculate_from_values
from slyp.contract import (
    Deductions,
    OtherDeduction,
    Pay,
    Period,
    PayslipExtract,
    Source,
    TaxCodeRead,
    UserContext,
)
from slyp.findings import (
    CalculationComparison,
    comparison_from_breakdown,
    generate_findings,
)
from slyp.analysis import analyse_payslip


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
    ni_category="A",
    pension_employee=None,
    student_loan=None,
    student_loan_plan=None,
    other=None,
    net_pay=None,
    unreadable_fields=None,
    reconciles=None,
) -> PayslipExtract:
    other_deductions = [
        OtherDeduction(type=kind, amount=Decimal(amount)) for kind, amount in (other or [])
    ]

    deductions_kwargs = dict(
        income_tax=Decimal(income_tax) if income_tax is not None else None,
        income_tax_ytd=Decimal(income_tax_ytd) if income_tax_ytd is not None else None,
        national_insurance=Decimal(national_insurance) if national_insurance is not None else None,
        ni_category=ni_category,
        pension_employee=Decimal(pension_employee) if pension_employee is not None else None,
        student_loan=Decimal(student_loan) if student_loan is not None else None,
        student_loan_plan=student_loan_plan,
        other=other_deductions,
    )

    if net_pay is None:
        gross_dec = Decimal(gross_this_period)
        total_deductions = sum(
            (v for v in (
                deductions_kwargs["income_tax"],
                deductions_kwargs["national_insurance"],
                deductions_kwargs["pension_employee"],
                deductions_kwargs["student_loan"],
            ) if v is not None),
            Decimal("0"),
        ) + sum((d.amount for d in other_deductions), Decimal("0"))
        net_pay = gross_dec - total_deductions
    else:
        net_pay = Decimal(net_pay)

    return PayslipExtract(
        source=Source(filename="test.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=period_number, frequency=frequency, tax_year="2026/27"),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(gross_this_period=Decimal(gross_this_period), gross_ytd=Decimal(gross_ytd)),
        deductions=Deductions(**deductions_kwargs),
        net_pay=net_pay,
        unreadable_fields=unreadable_fields or [],
        reconciles=reconciles,
    )


def _comparison(**overrides) -> CalculationComparison:
    return CalculationComparison(**overrides)


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


def test_reconciliation_passes_silently_when_figures_add_up():
    extract = _extract(gross_this_period="800.00", income_tax="0.00", national_insurance="0.00")
    findings = generate_findings(extract)
    assert not any(f.id == "payslip_does_not_reconcile" for f in findings)


def test_reconciliation_flags_a_real_gap():
    extract = _extract(net_pay="700.00")  # gross 800, no deductions, net should be 800
    findings = generate_findings(extract)
    finding = next(f for f in findings if f.id == "payslip_does_not_reconcile")
    assert finding.severity == "action"
    assert "100.00" in finding.explanation


def test_reconciliation_gated_when_net_pay_unreadable():
    extract = _extract(net_pay="700.00", unreadable_fields=["net_pay"])
    findings = generate_findings(extract)
    assert not any(f.id == "payslip_does_not_reconcile" for f in findings)


# --------------------------------------------------------------------------
# BR tax code — three branches
# --------------------------------------------------------------------------


def test_br_only_job_true_is_advisory_and_suggests_checking():
    extract = _extract(tax_code="BR", income_tax="160.00", gross_this_period="800.00", gross_ytd="800.00")
    findings = generate_findings(extract, UserContext(only_job=True))
    finding = next(f for f in findings if f.id == "tax_code_br_allowance_elsewhere")
    assert finding.severity == "advisory"


def test_br_only_job_false_is_clear_and_never_mentions_overpayment():
    extract = _extract(tax_code="BR", income_tax="160.00", gross_this_period="800.00", gross_ytd="800.00")
    findings = generate_findings(extract, UserContext(only_job=False))
    finding = next(f for f in findings if f.id == "tax_code_br_multiple_jobs")
    assert finding.severity == "clear"
    assert "overpay" not in finding.explanation.lower()
    assert finding.estimate is None


def test_br_only_job_unanswered_stays_conditional_and_claims_no_overpayment():
    extract = _extract(tax_code="BR", income_tax="160.00", gross_this_period="800.00", gross_ytd="800.00")
    findings = generate_findings(extract, UserContext(only_job=None))
    finding = next(f for f in findings if f.id == "tax_code_br_allowance_elsewhere")
    assert finding.severity == "advisory"
    assert "overpay" not in finding.explanation.lower()
    assert finding.estimate is None


# --------------------------------------------------------------------------
# Emergency basis detection + guarded overpayment estimate
# --------------------------------------------------------------------------


def _w1_scenario(only_job, unreadable_fields=None):
    """
    1257L W1, week 8, £500 this week, £4,000 YTD. A cumulative code would
    have taxed £2,066.15 of that (allowance caught up); £494.88 was
    actually deducted YTD under the emergency basis — an £81.65 gap.
    """
    extract = _extract(
        tax_code="1257L W1",
        frequency="weekly",
        period_number=8,
        gross_this_period="500.00",
        gross_ytd="4000.00",
        income_tax="61.86",
        income_tax_ytd="494.88",
        national_insurance="20.64",
        net_pay=str(Decimal("500.00") - Decimal("61.86") - Decimal("20.64")),
        unreadable_fields=unreadable_fields,
    )
    breakdown = calculate_from_values(
        gross_this_period="500.00",
        gross_ytd="4000.00",
        tax_code="1257L W1",
        period_number=8,
        frequency="weekly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)
    from dataclasses import replace
    from slyp.calculations import cumulative_tax_due_to_date, parse_tax_code

    tax_code = parse_tax_code("1257L W1")
    cumulative_equivalent = cumulative_tax_due_to_date(
        Decimal("4000.00"), 8, "weekly", replace(tax_code, cumulative=True)
    )
    comparison = replace(
        comparison,
        annualised_gross_ytd=Decimal("4000.00") + Decimal("500.00") * (52 - 8),
        personal_allowance_annual=tax_code.free_pay_annual,
        cumulative_equivalent_tax_ytd=cumulative_equivalent,
    )
    return extract, comparison


def test_emergency_basis_fires_for_w1_code():
    extract, comparison = _w1_scenario(only_job=True)
    findings = generate_findings(extract, UserContext(only_job=True), comparison)
    assert any(f.id == "tax_code_emergency_basis" for f in findings)


def test_emergency_basis_estimate_shown_when_only_job_true():
    extract, comparison = _w1_scenario(only_job=True)
    findings = generate_findings(extract, UserContext(only_job=True), comparison)
    finding = next(f for f in findings if f.id == "tax_code_emergency_basis")
    assert finding.estimate is not None
    assert finding.estimate.amount_gbp == Decimal("81.65")


@pytest.mark.parametrize("only_job", [False, None])
def test_emergency_basis_estimate_withheld_unless_only_job_true(only_job):
    extract, comparison = _w1_scenario(only_job=only_job)
    findings = generate_findings(extract, UserContext(only_job=only_job), comparison)
    finding = next(f for f in findings if f.id == "tax_code_emergency_basis")
    assert finding.estimate is None


def test_emergency_basis_estimate_withheld_when_income_tax_ytd_unreadable():
    extract, comparison = _w1_scenario(only_job=True, unreadable_fields=["deductions.income_tax_ytd"])
    findings = generate_findings(extract, UserContext(only_job=True), comparison)
    finding = next(f for f in findings if f.id == "tax_code_emergency_basis")
    assert finding.estimate is None


def test_emergency_basis_estimate_never_exceeds_actual_tax_deducted():
    # Clamp guard: even if the arithmetic produced something larger than
    # what was actually deducted, the estimate must not exceed it.
    extract, comparison = _w1_scenario(only_job=True)
    from dataclasses import replace
    comparison = replace(comparison, cumulative_equivalent_tax_ytd=Decimal("-1000.00"))
    findings = generate_findings(extract, UserContext(only_job=True), comparison)
    finding = next(f for f in findings if f.id == "tax_code_emergency_basis")
    assert finding.estimate.amount_gbp <= extract.deductions.income_tax_ytd


def test_no_emergency_basis_finding_for_a_cumulative_code():
    extract = _extract(tax_code="1257L")
    findings = generate_findings(extract)
    assert not any(f.id == "tax_code_emergency_basis" for f in findings)


# --------------------------------------------------------------------------
# Under Personal Allowance but taxed (annualise()-based gate)
# --------------------------------------------------------------------------


def _under_allowance_comparison(annualised_gross_ytd, personal_allowance_annual):
    return _comparison(
        annualised_gross_ytd=annualised_gross_ytd,
        personal_allowance_annual=personal_allowance_annual,
    )


def test_under_allowance_fires_when_projection_is_under_allowance_and_tax_is_deducted():
    extract = _extract(tax_code="1257L", income_tax="5.00", gross_this_period="800.00", gross_ytd="800.00")
    comparison = _under_allowance_comparison(Decimal("9600"), Decimal("12570"))
    findings = generate_findings(extract, comparison=comparison)
    finding = next(f for f in findings if f.id == "under_personal_allowance_but_taxed")
    assert finding.severity == "action"


def test_under_allowance_never_states_a_pound_figure():
    extract = _extract(tax_code="1257L", income_tax="5.00", gross_this_period="800.00", gross_ytd="800.00")
    comparison = _under_allowance_comparison(Decimal("9600"), Decimal("12570"))
    findings = generate_findings(extract, comparison=comparison)
    finding = next(f for f in findings if f.id == "under_personal_allowance_but_taxed")
    assert finding.estimate is None
    assert "£" not in finding.explanation


def test_under_allowance_does_not_fire_when_projection_exceeds_allowance():
    extract = _extract(tax_code="1257L", income_tax="5.00")
    comparison = _under_allowance_comparison(Decimal("30000"), Decimal("12570"))
    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "under_personal_allowance_but_taxed" for f in findings)


def test_under_allowance_does_not_fire_when_no_tax_is_being_deducted():
    extract = _extract(tax_code="1257L", income_tax="0.00")
    comparison = _under_allowance_comparison(Decimal("9600"), Decimal("12570"))
    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "under_personal_allowance_but_taxed" for f in findings)


def test_under_allowance_does_not_fire_for_a_code_with_no_allowance():
    # BR grants £0 allowance - the comparison would never legitimately be
    # populated with a positive personal_allowance_annual for BR, but the
    # check must not fire even if it somehow were given a zero one.
    extract = _extract(tax_code="BR", income_tax="160.00")
    comparison = _under_allowance_comparison(Decimal("9600"), Decimal("0"))
    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "under_personal_allowance_but_taxed" for f in findings)


def test_under_allowance_gated_when_gross_ytd_unreadable():
    extract = _extract(tax_code="1257L", income_tax="5.00", unreadable_fields=["pay.gross_ytd"])
    comparison = _under_allowance_comparison(Decimal("9600"), Decimal("12570"))
    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "under_personal_allowance_but_taxed" for f in findings)


def test_under_allowance_gated_when_comparison_has_no_projection():
    extract = _extract(tax_code="1257L", income_tax="5.00")
    findings = generate_findings(extract)  # default comparison, no annualise() figures
    assert not any(f.id == "under_personal_allowance_but_taxed" for f in findings)


# --------------------------------------------------------------------------
# Income tax / NI / student loan / pension differ-from-calculation checks
# --------------------------------------------------------------------------


def test_income_tax_higher_than_expected_produces_action_finding():
    extract = _extract(income_tax="50.00")
    comparison = _comparison(expected_income_tax=Decimal("20.00"))
    findings = generate_findings(extract, comparison=comparison)
    finding = next(f for f in findings if f.id == "income_tax_differs_from_calculation")
    assert finding.severity == "action"
    assert finding.estimate.amount_gbp == Decimal("30.00")


def test_income_tax_tiny_difference_is_not_flagged():
    extract = _extract(income_tax="20.00")
    comparison = _comparison(expected_income_tax=Decimal("20.005"))
    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "income_tax_differs_from_calculation" for f in findings)


def test_income_tax_check_gated_when_unreadable():
    extract = _extract(income_tax="50.00", unreadable_fields=["deductions.income_tax"])
    comparison = _comparison(expected_income_tax=Decimal("20.00"))
    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "income_tax_differs_from_calculation" for f in findings)


def test_national_insurance_difference_flagged():
    extract = _extract(national_insurance="50.00")
    comparison = _comparison(expected_national_insurance=Decimal("10.00"))
    findings = generate_findings(extract, comparison=comparison)
    assert any(f.id == "national_insurance_differs_from_calculation" for f in findings)


def test_pension_difference_is_advisory_not_action():
    extract = _extract(pension_employee="40.00")
    comparison = _comparison(expected_pension=Decimal("20.00"))
    findings = generate_findings(extract, comparison=comparison)
    finding = next(f for f in findings if f.id == "pension_differs_from_calculation")
    assert finding.severity == "advisory"


def test_expected_pension_is_never_populated_from_the_real_engine():
    """
    calculate_pay_breakdown() never calculates pension independently - it's
    scheme-specific and out of scope (see its own docstring). Comparing a
    real pension line against a hardcoded zero isn't a comparison, it's a
    guaranteed false mismatch on every payslip with a pension deduction.
    comparison_from_breakdown() must never populate expected_pension.
    """
    extract = _extract(pension_employee="40.00", net_pay="760.00", reconciles=True)
    breakdown = calculate_from_values(
        gross_this_period="800.00", gross_ytd="800.00",
        tax_code="1257L", period_number=1, frequency="monthly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)
    assert comparison.expected_pension is None

    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "pension_differs_from_calculation" for f in findings)


# --------------------------------------------------------------------------
# Net pay - expected_net must account for pension and other deductions the
# engine can't calculate itself, and must be None rather than wrong when it
# can't be confident it captured every deduction line.
# --------------------------------------------------------------------------


def test_net_pay_with_pension_reconciles_with_no_mismatch():
    # 800 gross, 1257L, month 1: engine computes income_tax=0, NI=0 (both
    # genuinely correct at this gross). Pension is real money the engine
    # doesn't calculate but must still subtract from expected_net.
    extract = _extract(
        gross_this_period="800.00", gross_ytd="800.00",
        pension_employee="40.00", net_pay="760.00", reconciles=True,
    )
    breakdown = calculate_from_values(
        gross_this_period="800.00", gross_ytd="800.00",
        tax_code="1257L", period_number=1, frequency="monthly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)

    assert comparison.expected_net == Decimal("760.00")
    assert comparison.net_difference == Decimal("0.00")

    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "net_pay_differs_from_calculation" for f in findings)


def test_net_pay_gated_when_pension_unreadable():
    extract = _extract(
        gross_this_period="800.00", gross_ytd="800.00",
        pension_employee="40.00", net_pay="760.00", reconciles=True,
        unreadable_fields=["deductions.pension_employee"],
    )
    breakdown = calculate_from_values(
        gross_this_period="800.00", gross_ytd="800.00",
        tax_code="1257L", period_number=1, frequency="monthly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)

    assert comparison.expected_net is None
    assert comparison.net_difference is None

    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "net_pay_differs_from_calculation" for f in findings)


def test_net_pay_with_other_deduction_reconciles_with_no_mismatch():
    extract = _extract(
        gross_this_period="800.00", gross_ytd="800.00",
        other=[("union", "10.00")], reconciles=True,
        # net_pay left as None - the fixture builder sums it including
        # the "other" line, so this proves the real value, not a
        # hand-picked one that happens to match.
    )
    breakdown = calculate_from_values(
        gross_this_period="800.00", gross_ytd="800.00",
        tax_code="1257L", period_number=1, frequency="monthly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)

    assert comparison.expected_net == Decimal("790.00")

    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "net_pay_differs_from_calculation" for f in findings)


def test_net_pay_gated_when_reconciliation_not_confirmed():
    """
    reconciles is None here (the default - nothing confirmed either way),
    which is the codebase's only signal for "every deduction line was
    captured". Anything less certain than an explicit True must not
    produce a net-pay comparison, even with a perfectly ordinary pension
    figure present.
    """
    extract = _extract(
        gross_this_period="800.00", gross_ytd="800.00",
        pension_employee="40.00", net_pay="760.00",
        # reconciles left at its default (None) - deliberately not True.
    )
    breakdown = calculate_from_values(
        gross_this_period="800.00", gross_ytd="800.00",
        tax_code="1257L", period_number=1, frequency="monthly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)

    assert comparison.expected_net is None

    findings = generate_findings(extract, comparison=comparison)
    assert not any(f.id == "net_pay_differs_from_calculation" for f in findings)


def test_net_pay_difference_flagged_once_every_deduction_is_confidently_captured():
    # A genuine, real mismatch: pension is confidently read and everything
    # reconciles, but the payslip's own net pay doesn't match what gross
    # minus every known deduction should give.
    extract = _extract(
        gross_this_period="800.00", gross_ytd="800.00",
        pension_employee="40.00", net_pay="700.00", reconciles=True,
    )
    breakdown = calculate_from_values(
        gross_this_period="800.00", gross_ytd="800.00",
        tax_code="1257L", period_number=1, frequency="monthly",
    )
    comparison = comparison_from_breakdown(breakdown, extract)

    findings = generate_findings(extract, comparison=comparison)
    finding = next(f for f in findings if f.id == "net_pay_differs_from_calculation")
    assert finding.severity == "action"
    assert finding.estimate.amount_gbp == Decimal("60.00")


# --------------------------------------------------------------------------
# Missing fields
# --------------------------------------------------------------------------


def test_unreadable_gross_pay_produces_its_own_finding():
    extract = _extract(unreadable_fields=["pay.gross_this_period"])
    findings = generate_findings(extract)
    assert any(f.id == "gross_pay_unreadable" for f in findings)


def test_unreadable_tax_code_produces_its_own_finding_and_suppresses_tax_code_rules():
    extract = _extract(unreadable_fields=["tax_code.value"])
    findings = generate_findings(extract)
    ids = {f.id for f in findings}
    assert "tax_code_unreadable" in ids
    assert not any(i.startswith("tax_code_") and i != "tax_code_unreadable" for i in ids)


# --------------------------------------------------------------------------
# Whole pipeline (slyp.analysis.analyse_payslip) — the plumbing bug
# --------------------------------------------------------------------------


def test_analyse_payslip_actually_reaches_the_calculation_engine():
    """
    Regression test: analyse_payslip() used to call calculate_pay_breakdown
    with the wrong arguments and always fall through to an empty
    comparison, so a real mismatch never produced a finding. This payslip
    has income tax deducted that doesn't match a 1257L calculation at all.
    """
    extract = _extract(
        tax_code="1257L",
        gross_this_period="2000.00",
        gross_ytd="2000.00",
        income_tax="999.00",
        net_pay="1000.36",
    )
    result = analyse_payslip(extract)
    assert result.status == "ok"
    assert any(f.id == "income_tax_differs_from_calculation" for f in result.findings)
    assert result.score.value < 100


def test_analyse_payslip_score_drops_when_income_tax_is_wrong():
    clean = _extract(tax_code="1257L", gross_this_period="800.00", gross_ytd="800.00", income_tax="0.00")
    wrong = _extract(
        tax_code="1257L",
        gross_this_period="2000.00",
        gross_ytd="2000.00",
        income_tax="999.00",
        net_pay="1000.36",
    )
    clean_result = analyse_payslip(clean)
    wrong_result = analyse_payslip(wrong)
    assert wrong_result.score.value < clean_result.score.value


def test_analyse_payslip_end_to_end_emergency_code_with_estimate():
    extract = _extract(
        tax_code="1257L W1",
        frequency="weekly",
        period_number=8,
        gross_this_period="500.00",
        gross_ytd="4000.00",
        income_tax="61.86",
        income_tax_ytd="494.88",
        national_insurance="20.64",
        net_pay=str(Decimal("500.00") - Decimal("61.86") - Decimal("20.64")),
    )
    result = analyse_payslip(extract, UserContext(only_job=True))
    assert result.status == "ok"
    emergency = next(f for f in result.findings if f.id == "tax_code_emergency_basis")
    assert emergency.estimate is not None
    assert emergency.estimate.amount_gbp == Decimal("81.65")


def test_analyse_payslip_unsupported_tax_code_trips_the_gate_not_a_crash():
    extract = _extract(tax_code="S1257L")
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert result.findings == []
