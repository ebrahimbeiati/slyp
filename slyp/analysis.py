# analysis.py

from __future__ import annotations

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
    calculate_pay_breakdown,
    parse_tax_code,
)

from .findings import (
    CalculationComparison,
    comparison_from_breakdown,
    generate_findings,
)

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
    # 2. Parse the tax code
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
    # 3. Calculate expected deductions
    # ------------------------------------------------------------------

    breakdown = None

    calculation_error: Optional[str] = None

    try:
        breakdown = calculate_pay_breakdown(
            extract=extract,
            tax_code=tax_code,
        )

    except TypeError:
        # Compatibility fallback for a calculations.py implementation
        # that expects the internal PayPeriodFacts object instead.
        try:
            breakdown = _calculate_using_pay_period_facts(
                extract,
                tax_code,
            )

        except Exception as exc:
            calculation_error = str(exc)

    except Exception as exc:
        calculation_error = str(exc)

    # ------------------------------------------------------------------
    # 4. Generate findings
    # ------------------------------------------------------------------

    if breakdown is not None:

        comparison = comparison_from_breakdown(
            breakdown,
        )

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
    # 5. Build verdict
    # ------------------------------------------------------------------

    verdict = build_verdict(
        findings=findings,
        extract=extract,
    )

    # ------------------------------------------------------------------
    # 6. Build score
    # ------------------------------------------------------------------

    score = build_score(
        findings=findings,
        extract=extract,
    )

    # ------------------------------------------------------------------
    # 7. Build final response
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
# Compatibility adapter
# ============================================================================


def _calculate_using_pay_period_facts(
    extract: PayslipExtract,
    tax_code,
):
    """
    Adapter for the calculations.py design described in types.py.

    The calculation engine receives PayPeriodFacts rather than the
    extraction object directly.
    """

    from types import PayPeriodFacts

    frequency = extract.period.frequency

    if frequency is None:
        raise ValueError("Pay frequency is required to calculate deductions.")

    period_number = extract.period.period_number

    if period_number is None:
        raise ValueError("Pay period number is required to calculate deductions.")

    gross_this_period = extract.pay.gross_this_period
    gross_ytd = extract.pay.gross_ytd

    if gross_this_period is None:
        raise ValueError("Gross pay for this period is required.")

    if gross_ytd is None:
        raise ValueError("Year-to-date gross pay is required.")

    facts = PayPeriodFacts(
        gross_this_period=gross_this_period,
        gross_ytd=gross_ytd,
        tax_code=tax_code,
        period_number=period_number,
        frequency=frequency,
        ni_category=extract.deductions.ni_category or "A",
        student_loan_plan=extract.deductions.student_loan_plan,
    )

    # Try the most likely public calculation function names.

    from calculations import calculate

    return calculate(facts)


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


def build_score(
    findings: list[Finding],
    extract: PayslipExtract,
) -> Score:
    """
    Produces the simple payslip health score.

    This is deliberately based on deterministic checks rather than
    an AI-generated score.
    """

    checks_run = 0
    checks_passed = 0
    movers: list[str] = []

    # --------------------------------------------------------------
    # Check 1: reconciliation
    # --------------------------------------------------------------

    reconciliation_available = (
        extract.pay.gross_this_period is not None
        and extract.net_pay is not None
        and extract.deductions.income_tax is not None
        and extract.deductions.national_insurance is not None
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

    if extract.tax_code.value:

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

    if extract.deductions.income_tax is not None:

        checks_run += 1

        income_tax_finding = next(
            (finding for finding in findings if finding.id == "income_tax_difference"),
            None,
        )

        if income_tax_finding is None:
            checks_passed += 1
        else:
            movers.append("Check the income tax deduction against your tax code.")

    # --------------------------------------------------------------
    # Check 4: National Insurance
    # --------------------------------------------------------------

    if extract.deductions.national_insurance is not None:

        checks_run += 1

        ni_finding = next(
            (
                finding
                for finding in findings
                if finding.id == "national_insurance_difference"
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

    if checks_run == 0:
        score_value = 0
    else:
        score_value = round(
            Decimal(checks_passed) / Decimal(checks_run) * Decimal("100")
        )

    return Score(
        value=int(score_value),
        checks_passed=checks_passed,
        checks_run=checks_run,
        movers=movers,
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
