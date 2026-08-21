# analysis.py

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Optional

from .contract import (
    AnalysisResult,
    Finding,
    PayslipExtract,
    Score,
    UserContext,
    Verdict,
)

from .calculations import (
    annualise,
    calculate_pay_breakdown,
    cumulative_tax_due_to_date,
    parse_tax_code,
    validate_tax_year,
)

from .findings import (
    CalculationComparison,
    ZERO_GBP as ZERO,
    comparison_from_breakdown,
    generate_findings,
)

from .types import PayPeriodFacts, UnsupportedPayslip

# ============================================================================
# Public API
# ============================================================================


def analyse_payslip(
    extract: PayslipExtract,
    user_context: Optional[UserContext] = None,
) -> AnalysisResult:
    """
    Run the complete payslip analysis pipeline.

    Pipeline:

        PayslipExtract
            ↓
        validation
            ↓
        tax code parsing
            ↓
        calculations.py
            ↓
        findings.py
            ↓
        score / verdict
            ↓
        AnalysisResult

    Important:
        This function never invents missing payslip values.

        If a calculation depends on a field that extraction could not read,
        the calculation is skipped and the result explains why.
    """

    context = user_context or UserContext()

    # ------------------------------------------------------------------
    # 1. Basic validation
    # ------------------------------------------------------------------

    validation_error = validate_extract(extract)

    if validation_error is not None:
        return AnalysisResult(
            status="unreadable",
            failure_reason=validation_error,
            extract=extract,
            verdict=Verdict(
                headline="We could not reliably read this payslip",
                severity="action",
            ),
            findings=[],
            projections=[],
            score=None,
        )

    # ------------------------------------------------------------------
    # 2. Confirm the tax year is one this engine has rates for
    # ------------------------------------------------------------------
    #
    # Checked before tax code parsing and deliberately kept as its own
    # step with its own message: "this payslip is from a tax year we
    # don't yet support" is a different fact than "this tax code isn't
    # supported", and conflating them would leave the user checking the
    # wrong thing.

    try:
        validate_tax_year(extract.period.tax_year)

    except UnsupportedPayslip as exc:
        return AnalysisResult(
            status="unsupported",
            failure_reason=str(exc),
            extract=extract,
            verdict=Verdict(
                headline="This payslip is from a tax year we don't yet support",
                severity="action",
            ),
            findings=[],
            projections=[],
            score=None,
        )

    # ------------------------------------------------------------------
    # 3. Parse the tax code
    # ------------------------------------------------------------------

    tax_code_value = extract.tax_code.value

    if not tax_code_value:
        return AnalysisResult(
            status="unreadable",
            failure_reason=(
                "The tax code could not be read from the payslip. "
                "Please check the tax code and try again."
            ),
            extract=extract,
            verdict=Verdict(
                headline="The tax code could not be read",
                severity="action",
            ),
            findings=[],
            projections=[],
            score=None,
        )

    try:
        tax_code = parse_tax_code(tax_code_value)

    except Exception as exc:
        return AnalysisResult(
            status="unsupported",
            failure_reason=(
                f"The tax code '{tax_code_value}' is not currently "
                f"supported by the tax engine."
            ),
            extract=extract,
            verdict=Verdict(
                headline="This tax code needs a manual check",
                severity="action",
            ),
            findings=[],
            projections=[],
            score=None,
        )

    # ------------------------------------------------------------------
    # 4. Calculate expected deductions
    # ------------------------------------------------------------------

    breakdown = None

    comparison: Optional[CalculationComparison] = None

    calculation_error: Optional[str] = None

    try:
        facts = _facts_from_extract(extract, tax_code)

        breakdown = calculate_pay_breakdown(facts)

        comparison = comparison_from_breakdown(breakdown, extract)

        # Full-year projection, for the under-Personal-Allowance gate.
        # This is a gate, not a displayed figure — see annualise()'s
        # docstring.
        annualised_gross_ytd = annualise(
            facts.gross_this_period,
            facts.gross_ytd,
            facts.period_number,
            facts.frequency,
        )

        # What a cumulative code would have deducted YTD on the same
        # figures — only meaningful (and only computed) for a
        # non-cumulative code, since that's the comparison the
        # emergency-code overpayment estimate depends on.
        cumulative_equivalent_tax_ytd = None

        if not tax_code.cumulative:
            cumulative_equivalent_tax_ytd = cumulative_tax_due_to_date(
                facts.gross_ytd,
                facts.period_number,
                facts.frequency,
                replace(tax_code, cumulative=True),
            )

        comparison = replace(
            comparison,
            annualised_gross_ytd=annualised_gross_ytd,
            personal_allowance_annual=tax_code.free_pay_annual,
            cumulative_equivalent_tax_ytd=cumulative_equivalent_tax_ytd,
        )

    except Exception as exc:
        calculation_error = str(exc)

    # ------------------------------------------------------------------
    # 5. Generate findings
    # ------------------------------------------------------------------

    if breakdown is not None:

        findings = generate_findings(
            extract=extract,
            user_context=context,
            comparison=comparison,
        )

    else:

        # We can still provide structural findings even when the tax
        # calculation cannot run.
        comparison = CalculationComparison()

        findings = generate_findings(
            extract=extract,
            user_context=context,
            comparison=comparison,
        )

        if calculation_error:
            findings.append(
                Finding(
                    id="calculation_unavailable",
                    severity="advisory",
                    title="We could not complete every calculation",
                    explanation=(
                        "The payslip was readable, but the tax engine "
                        "could not calculate every expected deduction "
                        "for this payslip."
                    ),
                    next_step=(
                        "Check the extracted figures and tax code before "
                        "relying on the result."
                    ),
                    source_fields=[],
                )
            )

    # ------------------------------------------------------------------
    # 6. Build verdict
    # ------------------------------------------------------------------

    verdict = build_verdict(
        findings=findings,
        extract=extract,
    )

    # ------------------------------------------------------------------
    # 7. Build score
    # ------------------------------------------------------------------

    score = build_score(
        findings=findings,
        extract=extract,
        comparison=comparison,
    )

    # ------------------------------------------------------------------
    # 8. Build final response
    # ------------------------------------------------------------------

    return AnalysisResult(
        status="ok",
        failure_reason=None,
        extract=extract,
        verdict=verdict,
        findings=findings,
        projections=[],
        score=score,
    )


# ============================================================================
# Validation
# ============================================================================


def validate_extract(
    extract: PayslipExtract,
) -> Optional[str]:
    """
    Validate that the minimum fields required for analysis exist.

    We deliberately do NOT require every possible payslip field.

    For example:
        - pension may legitimately be absent
        - student loan may legitimately be absent
        - hourly rate may legitimately be absent
        - YTD values may be unavailable on some payslips

    But gross pay, net pay and tax code are essential for the MVP.
    """

    if extract is None:
        return "No payslip data was supplied."

    missing = set(extract.unreadable_fields)

    required_fields = {
        "pay.gross_this_period": extract.pay.gross_this_period,
        "net_pay": extract.net_pay,
        "tax_code.value": extract.tax_code.value,
    }

    missing_required = [
        field
        for field, value in required_fields.items()
        if value is None or field in missing
    ]

    if missing_required:
        return (
            "The following required payslip fields could not be read "
            "reliably: " + ", ".join(missing_required) + "."
        )

    gross = extract.pay.gross_this_period
    net = extract.net_pay

    if gross is not None and gross < Decimal("0"):
        return "Gross pay cannot be negative."

    if net is not None and net < Decimal("0"):
        return "Net pay cannot be negative."

    if gross is not None and net is not None and net > gross:
        return (
            "The extracted net pay is greater than gross pay. "
            "The payslip should be checked before calculation."
        )

    return None


# ============================================================================
# Facts adapter
# ============================================================================


def _facts_from_extract(
    extract: PayslipExtract,
    tax_code,
) -> PayPeriodFacts:
    """
    Build the calculation engine's PayPeriodFacts from what extraction read
    off the payslip.

    Every field consumed here is checked against unreadable_fields, not
    just None-ness. extract_payslip() already nulls out anything it
    flags unreadable (a generic loop over the full unreadable set, not a
    hand-picked subset), so in practice the two checks agree for data
    that came through that pipeline. But nothing in the contract
    enforces that a field can't be present while also listed as
    unreadable - PayslipExtract is a plain pydantic model with no
    validator tying the two together - and this function is reachable
    from analyse_payslip(), a public entry point callable with any
    hand-built PayslipExtract. findings.py's _check_* functions have
    always checked both explicitly for exactly this reason; this
    function previously only checked None-ness.

    Raises ValueError for a field the calculation can't run without — the
    caller treats that the same as any other calculation_error: no
    breakdown, no comparison, and the findings layer falls back to
    structural-only findings for this payslip.
    """

    def _unreadable(field: str) -> bool:
        return field in extract.unreadable_fields

    frequency = extract.period.frequency

    if frequency is None or _unreadable("period.frequency"):
        raise ValueError("Pay frequency is required to calculate deductions.")

    period_number = extract.period.period_number

    if period_number is None or _unreadable("period.period_number"):
        raise ValueError("Pay period number is required to calculate deductions.")

    gross_this_period = extract.pay.gross_this_period
    gross_ytd = extract.pay.gross_ytd

    if gross_this_period is None or _unreadable("pay.gross_this_period"):
        raise ValueError("Gross pay for this period is required.")

    if gross_ytd is None or _unreadable("pay.gross_ytd"):
        raise ValueError("Year-to-date gross pay is required.")

    # ni_category and student_loan_plan being None is a legitimate value
    # (assume category A; assume no student loan) - only refuse when the
    # field is present but not confidently readable, since guessing "A"
    # or "no loan" over a value we're not sure of is exactly the kind of
    # silent wrong-field risk this function exists to avoid.
    if _unreadable("deductions.ni_category"):
        raise ValueError("NI category is not confidently readable.")

    if _unreadable("deductions.student_loan_plan"):
        raise ValueError("Student loan plan is not confidently readable.")

    return PayPeriodFacts(
        gross_this_period=gross_this_period,
        gross_ytd=gross_ytd,
        tax_code=tax_code,
        period_number=period_number,
        frequency=frequency,
        ni_category=extract.deductions.ni_category or "A",
        student_loan_plan=extract.deductions.student_loan_plan,
    )


# ============================================================================
# Verdict
# ============================================================================


def build_verdict(
    findings: list[Finding],
    extract: PayslipExtract,
) -> Verdict:

    action_count = sum(1 for finding in findings if finding.severity == "action")

    advisory_count = sum(1 for finding in findings if finding.severity == "advisory")

    if action_count > 0:

        return Verdict(
            headline=(
                f"{action_count} thing"
                f"{'s' if action_count != 1 else ''} "
                f"to check on this payslip"
            ),
            severity="action",
        )

    if advisory_count > 0:

        return Verdict(
            headline=(
                f"{advisory_count} thing"
                f"{'s' if advisory_count != 1 else ''} "
                f"worth checking"
            ),
            severity="advisory",
        )

    return Verdict(
        headline="Nothing obvious needs checking",
        severity="clear",
    )


# ============================================================================
# Score
# ============================================================================


def _comparison_is_vacuous(
    expected: Optional[Decimal],
    actual: Optional[Decimal],
) -> bool:
    """
    True when comparing these two establishes nothing.

    Two distinct ways that happens, and both used to count as a pass:

      - The engine produced no expected figure at all (`expected is
        None`). Nothing was compared. This is the case behind "4/4 checks
        clear" appearing on a payslip that also says "we could not
        complete every calculation" - the checks counted the ABSENCE of a
        finding as a pass, and a calculation that never ran cannot
        produce a finding.
      - Both figures are zero. Real, but nothing could have been wrong:
        under the personal allowance and under the primary threshold,
        £0.00 is compared against £0.00 and always agrees.
    """
    if expected is None:
        return True
    return expected == ZERO and (actual is None or actual == ZERO)


def build_score(
    findings: list[Finding],
    extract: PayslipExtract,
    comparison: Optional[CalculationComparison] = None,
) -> Score:
    """
    Produces the simple payslip health score.

    This is deliberately based on deterministic checks rather than
    an AI-generated score.

    checks_run counts only checks that had something to check. A check
    with nothing to compare is recorded in `not_applicable` with a plain
    reason instead of being silently counted as a pass - "we verified
    nothing and found nothing wrong" is not the same statement as "we
    verified this and it was right", and only one of them belongs in a
    score the user reads as confidence.

    `value` is None - not 0 - when nothing applied. A zero would read as
    a failing payslip, which is the same overstatement in the opposite
    direction.
    """

    checks_run = 0
    checks_passed = 0
    movers: list[str] = []
    not_applicable: list[str] = []

    comparison = comparison if comparison is not None else CalculationComparison()

    # --------------------------------------------------------------
    # Check 1: reconciliation
    # --------------------------------------------------------------

    reconciliation_available = (
        extract.pay.gross_this_period is not None
        and extract.net_pay is not None
        and extract.deductions.income_tax is not None
        and extract.deductions.national_insurance is not None
    )

    if not reconciliation_available:
        not_applicable.append(
            "Gross, net and the main deductions weren't all readable, so we "
            "couldn't check that the payslip adds up."
        )

    if reconciliation_available:

        checks_run += 1

        reconciliation_finding = next(
            (
                finding
                for finding in findings
                if finding.id == "payslip_does_not_reconcile"
            ),
            None,
        )

        if reconciliation_finding is None:
            checks_passed += 1
        else:
            movers.append(
                "Check the difference between gross pay, deductions and net pay."
            )

    # --------------------------------------------------------------
    # Check 2: tax code
    # --------------------------------------------------------------

    if not extract.tax_code.value or is_unreadable(extract, "tax_code.value"):
        not_applicable.append(
            "The tax code wasn't readable, so we couldn't check it."
        )

    if extract.tax_code.value and not is_unreadable(extract, "tax_code.value"):

        checks_run += 1

        tax_code_findings = [
            finding for finding in findings if finding.id.startswith("tax_code_")
        ]

        serious_tax_code_finding = any(
            finding.severity == "action" for finding in tax_code_findings
        )

        if not serious_tax_code_finding:
            checks_passed += 1
        else:
            movers.append(
                "Check whether the tax code is correct for your circumstances."
            )

    # --------------------------------------------------------------
    # Check 3: income tax
    # --------------------------------------------------------------

    income_tax_vacuous = _comparison_is_vacuous(
        comparison.expected_income_tax,
        extract.deductions.income_tax,
    )

    if extract.deductions.income_tax is None or income_tax_vacuous:
        not_applicable.append(
            "No income tax was due or deducted this period, so there was "
            "nothing to check against your tax code."
            if income_tax_vacuous and comparison.expected_income_tax == ZERO
            else "We couldn't work out the income tax due, so it wasn't checked."
        )

    if extract.deductions.income_tax is not None and not income_tax_vacuous:

        checks_run += 1

        income_tax_finding = next(
            (
                finding
                for finding in findings
                if finding.id == "income_tax_differs_from_calculation"
            ),
            None,
        )

        if income_tax_finding is None:
            checks_passed += 1
        else:
            movers.append("Check the income tax deduction against your tax code.")

    # --------------------------------------------------------------
    # Check 4: National Insurance
    # --------------------------------------------------------------

    ni_vacuous = _comparison_is_vacuous(
        comparison.expected_national_insurance,
        extract.deductions.national_insurance,
    )

    if extract.deductions.national_insurance is None or ni_vacuous:
        not_applicable.append(
            "Earnings were below the National Insurance threshold, so there "
            "was no NI to check."
            if ni_vacuous and comparison.expected_national_insurance == ZERO
            else "We couldn't work out the National Insurance due, so it "
            "wasn't checked."
        )

    if extract.deductions.national_insurance is not None and not ni_vacuous:

        checks_run += 1

        ni_finding = next(
            (
                finding
                for finding in findings
                if finding.id == "national_insurance_differs_from_calculation"
            ),
            None,
        )

        if ni_finding is None:
            checks_passed += 1
        else:
            movers.append("Check the National Insurance deduction.")

    # --------------------------------------------------------------
    # Calculate score
    # --------------------------------------------------------------

    # None, not 0: nothing applied, so there is no score to give. A 0
    # would be read as a failing payslip.
    score_value = (
        None
        if checks_run == 0
        else int(round(Decimal(checks_passed) / Decimal(checks_run) * Decimal("100")))
    )

    return Score(
        value=score_value,
        checks_passed=checks_passed,
        checks_run=checks_run,
        movers=movers,
        not_applicable=not_applicable,
    )


# ============================================================================
# Utility helpers
# ============================================================================


def is_unreadable(
    extract: PayslipExtract,
    field_name: str,
) -> bool:

    return field_name in extract.unreadable_fields


def any_unreadable(
    extract: PayslipExtract,
    field_names: list[str],
) -> bool:

    return any(field_name in extract.unreadable_fields for field_name in field_names)


# ============================================================================
# Optional convenience API
# ============================================================================


def analyse(
    extract: PayslipExtract,
    only_job: Optional[bool] = None,
) -> AnalysisResult:
    """
    Small convenience wrapper for the API layer.

    Example:

        result = analyse(
            extract,
            only_job=True,
        )
    """

    context = UserContext(
        only_job=only_job,
    )

    return analyse_payslip(
        extract=extract,
        user_context=context,
    )


__all__ = [
    "analyse",
    "analyse_payslip",
    "validate_extract",
    "build_verdict",
    "build_score",
    "CalculationComparison",
]
