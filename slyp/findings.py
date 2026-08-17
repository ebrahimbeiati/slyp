"""
Findings layer — OWNER: Kelvin

Turns a PayslipExtract (slyp/contract.py) into an AnalysisResult: the
findings, verdict, projections and score the frontend renders. This is the
product — everything before it (extraction, calculation) just moves and
checks numbers.

THE ONE RULE THAT GOVERNS THIS FILE: code decides, code calculates, the
model never touches it. No LLM call belongs anywhere below. Every finding,
severity and monetary figure comes out of deterministic Python. If a judge
asks "how did you get that number?", the answer is a function, not a prompt.

Pure function in, pure function out: analyse() does no I/O, no network, no
file reads, no model calls.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, NamedTuple, Optional

from .calculations import RATES, annualise, income_tax_due, national_insurance_due, parse_tax_code
from .contract import (
    AnalysisResult,
    Estimate,
    Finding,
    PayslipExtract,
    Projection,
    ProjectionPoint,
    Score,
    UserContext,
    Verdict,
)
from .types import PayPeriodFacts, TaxCode, UnsupportedPayslip, periods_in_year


# --------------------------------------------------------------------------
# The confidence gate — implement this first, everything depends on it
# --------------------------------------------------------------------------

# Mirrors extraction.py's own threshold. Kept as a second, independent
# check here rather than trusting that extraction already enforced it -
# this file has to stay safe on its own even if that upstream invariant
# ever changes, because a rule firing on a misread field is the worst
# thing this system can do.
_CONFIDENCE_THRESHOLD = 0.7


def _get_field(extract: PayslipExtract, dotted_path: str):
    """Resolve a dotted path ("pay.gross_ytd") against the extract, or
    None if any hop along the way is missing."""
    value: object = extract
    for part in dotted_path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def can_run(extract: PayslipExtract, required: list[str]) -> bool:
    """
    True only when every field in `required` is present, not listed in
    unreadable_fields, and at or above the confidence threshold.

    Every rule below (other than R1, whose job is precisely to detect an
    unreadable tax code) calls this before doing anything else. If it
    returns False, the rule produces no finding at all - not a hedged
    one.
    """
    for path in required:
        if path in extract.unreadable_fields:
            return False
        if _get_field(extract, path) is None:
            return False
        if extract.confidence.get(path, 1.0) < _CONFIDENCE_THRESHOLD:
            return False
    return True


def _safe(fn: Callable[..., Decimal], *args, **kwargs) -> Optional[Decimal]:
    """
    Calls a calculation-layer function that may still be a stub or may be
    out of MVP scope for this payslip. Returns None on NotImplementedError
    or UnsupportedPayslip instead of raising, so a rule can degrade its
    finding (drop the estimate, skip the projection) rather than crash the
    whole analysis over one missing calculation. See "Handling the
    unimplemented calculations" in the phase 4 brief.
    """
    try:
        return fn(*args, **kwargs)
    except (NotImplementedError, UnsupportedPayslip):
        return None


class _RuleResult(NamedTuple):
    """
    outcome is one of:
      "gated"  - required data wasn't available; the check did not run
                 at all and must not count as passed OR failed
      "passed" - the check ran and found nothing wrong
      "failed" - the check ran and found something worth surfacing
                 (usually, but not always, with a finding attached - see
                 _check_national_insurance for the one exception)

    This is how score.checks_run / checks_passed stay honest: a gated
    check is excluded from both counts rather than silently counting as
    passed.

    `note` is only ever populated on a "gated" outcome caused by a
    genuinely unreadable field on THIS payslip - never for a check gated
    because a calculation is still a stub (that's an expected, developer-
    known gap, not something the user can act on - see the phase 4.1
    brief's closing note). It's plain English, e.g. "We couldn't check
    your National Insurance because your pay frequency wasn't readable,"
    and feeds analyse()'s score.movers so a gated check is visible rather
    than silently absent.
    """

    outcome: str
    finding: Optional[Finding]
    note: Optional[str] = None


_SEVERITY_WEIGHT = {"action": 15, "advisory": 5, "clear": 0}
_MAX_SURFACED_FINDINGS = 4
_MAX_CLEAR_FINDINGS = 3
_MAX_MOVERS = 4
_SEVERITY_ORDER = {"action": 0, "advisory": 1, "clear": 2}

_MULTI_JOB_WARNING = (
    "Multiple payslips were supplied - only the first was analysed. "
    "Checking more than one job together isn't supported yet."
)

# Plain-English names for the dotted paths a gate can fail on, used only
# to build a _gated_note() sentence - never shown to the user as a raw
# dotted path.
_FIELD_LABELS = {
    "pay.gross_this_period": "this period's gross pay",
    "pay.gross_ytd": "your year-to-date gross pay",
    "period.period_number": "which pay period this is",
    "period.frequency": "your pay frequency",
    "deductions.income_tax_ytd": "your year-to-date income tax",
    "deductions.national_insurance": "the National Insurance deducted",
    "deductions.pension_employee": "your pension contribution",
    "deductions.pension_employer": "your employer's pension contribution",
}


def _gated_note(check_label: str, extract: PayslipExtract, required: list[str]) -> str:
    """
    Builds "We couldn't check {check_label} because {field} wasn't
    readable." from the first field in `required` that fails the gate.
    Only call this after can_run(extract, required) has already returned
    False - see the callers below.
    """
    for path in required:
        unreadable = (
            path in extract.unreadable_fields
            or _get_field(extract, path) is None
            or extract.confidence.get(path, 1.0) < _CONFIDENCE_THRESHOLD
        )
        if unreadable:
            field_label = _FIELD_LABELS.get(path, path)
            return f"We couldn't check {check_label} because {field_label} wasn't readable."
    return f"We couldn't check {check_label} - not enough readable data."


# --------------------------------------------------------------------------
# R1 — tax code missing or unparseable
# --------------------------------------------------------------------------


def _tax_code_field_unreadable(extract: PayslipExtract) -> bool:
    if "tax_code.value" in extract.unreadable_fields:
        return True
    if extract.tax_code.value is None:
        return True
    if extract.confidence.get("tax_code.value", 1.0) < _CONFIDENCE_THRESHOLD:
        return True
    return False


def _check_tax_code_readable(extract: PayslipExtract) -> tuple[_RuleResult, Optional[TaxCode]]:
    """
    R1. Unlike every other rule, this one's JOB is to detect an unreadable
    or unparseable tax code - so unlike the rest, "unreadable" is the
    finding, not a reason to stay silent. It never returns "gated": it
    always runs, because it has nothing else to depend on.

    Returns the parsed TaxCode on success so R2-R4 don't each re-parse it,
    and None whenever this rule fires - callers use that None as the
    signal to stop running every other tax-code rule, per the "stop"
    instruction in the brief.
    """
    if _tax_code_field_unreadable(extract):
        finding = Finding(
            id="tax_code_unreadable",
            severity="advisory",
            title="We couldn't read your tax code",
            explanation=(
                "We couldn't confidently read the tax code on this payslip. "
                "It's the field that determines almost everything else we'd "
                "check, so we've stopped there rather than guess at the rest."
            ),
            next_step=(
                "Check the tax code printed on your payslip against your "
                "HMRC personal tax account."
            ),
            source_fields=["tax_code.value"],
        )
        return _RuleResult("failed", finding), None

    raw_value = extract.tax_code.value
    try:
        tax_code = parse_tax_code(raw_value)
    except UnsupportedPayslip:
        finding = Finding(
            id="tax_code_unparseable",
            severity="advisory",
            title="We didn't recognise this tax code",
            explanation=(
                f'The tax code on this payslip, "{raw_value}", isn\'t one we '
                "recognise or support checking yet. It's the field that "
                "determines everything else, so we've stopped there."
            ),
            next_step="Check the tax code against your HMRC personal tax account.",
            source_fields=["tax_code.value"],
        )
        return _RuleResult("failed", finding), None

    return _RuleResult("passed", None), tax_code


# --------------------------------------------------------------------------
# R2 — emergency basis (W1 / M1 / X)
# --------------------------------------------------------------------------


def _cumulative_tax_to_date(
    cumulative_code: TaxCode,
    gross_per_period: Decimal,
    period_number: int,
    frequency: str,
) -> Decimal:
    """
    Total income tax that SHOULD have been paid by `period_number` under a
    cumulative code, assuming `gross_per_period` every period.

    income_tax_due() only ever returns a single period's INCREMENTAL tax
    (tax due to date minus tax due to date-1, per its own docstring) -
    there's no function that hands back a running total directly. Summing
    every period from 1 to period_number recovers it: the increments
    telescope back into the cumulative total by construction. This costs
    up to ~52 calls to a Decimal-only function - not a performance
    concern at this scale.

    Deliberately uses a flat gross_per_period for every period rather than
    the real (unknown) pay history behind this year's YTD figure. That's
    the same simplifying assumption every "if this carries on" estimate in
    this file makes, and it's why the resulting Estimate/Projection are
    always marked as estimates.
    """
    total = Decimal("0")
    for period in range(1, period_number + 1):
        facts = PayPeriodFacts(
            gross_this_period=gross_per_period,
            gross_ytd=gross_per_period * period,
            tax_code=cumulative_code,
            period_number=period,
            frequency=frequency,
        )
        total += income_tax_due(facts)
    return total


def _as_cumulative(tax_code: TaxCode) -> TaxCode:
    """The same code, but as if it were applied on a normal cumulative
    basis - used to work out what SHOULD have been deducted."""
    return TaxCode(
        raw=tax_code.raw,
        kind=tax_code.kind,
        free_pay_annual=tax_code.free_pay_annual,
        cumulative=True,
        region=tax_code.region,
    )


_EMERGENCY_BASIS_ESTIMATE_FIELDS = [
    "pay.gross_this_period",
    "pay.gross_ytd",
    "deductions.income_tax_ytd",
    "period.period_number",
    "period.frequency",
]


def _emergency_basis_overpayment(extract: PayslipExtract, tax_code: TaxCode) -> Optional[Decimal]:
    """
    What cumulative tax would have been to date, subtracted from what was
    actually deducted. Positive means overpaid. Approximates the "actual"
    gross-per-period as gross_ytd / period_number (an even spread) since
    we only have the year-to-date total, not a per-period history - see
    _cumulative_tax_to_date.
    """
    period_number = extract.period.period_number
    gross_per_period = extract.pay.gross_ytd / period_number
    expected = _safe(
        _cumulative_tax_to_date,
        _as_cumulative(tax_code),
        gross_per_period,
        period_number,
        extract.period.frequency,
    )
    if expected is None:
        return None
    return (extract.deductions.income_tax_ytd - expected).quantize(Decimal("0.01"))


def _emergency_basis_explanation(extract: PayslipExtract) -> str:
    """
    Two variants, both keeping the finding (it's still worth flagging
    either way - see phase 4.1 item 5). The standard one reads as though
    the code is actively costing money, which is wrong on a payslip where
    this period's own allowance happened to cover this period's own pay -
    common on a weekly W1 code with a light week. Only switches to the
    zero-cost variant when this period's income_tax is readable and
    genuinely zero; an unreadable figure gets the standard (more
    cautious) wording rather than assuming it was free.
    """
    opening = (
        "This code taxes each pay period on its own, ignoring what you've "
        "earned or paid in tax so far this year. It's normally temporary - "
        "applied when payroll doesn't yet have your full details."
    )

    no_cost_yet = can_run(extract, ["deductions.income_tax"]) and extract.deductions.income_tax == 0
    if no_cost_yet:
        return (
            f"{opening} It hasn't cost you anything on this payslip - one "
            "pay period's allowance was enough to cover what you earned "
            "this time - but it's still worth getting corrected before a "
            "busier or higher-earning period, once HMRC has your P45 or a "
            "starter checklist."
        )

    return (
        f"{opening} It's usually corrected once HMRC has your P45 or a "
        "starter checklist."
    )


def _check_emergency_basis(extract: PayslipExtract, tax_code: TaxCode) -> _RuleResult:
    if tax_code.cumulative:
        return _RuleResult("passed", None)

    estimate = None
    source_fields = ["tax_code.value"]
    if can_run(extract, _EMERGENCY_BASIS_ESTIMATE_FIELDS):
        overpayment = _emergency_basis_overpayment(extract, tax_code)
        if overpayment is not None and overpayment > 0:
            estimate = Estimate(
                label="Possible overpayment so far this tax year",
                amount_gbp=overpayment,
            )
        source_fields = source_fields + _EMERGENCY_BASIS_ESTIMATE_FIELDS

    finding = Finding(
        id="tax_code_emergency_basis",
        severity="action",
        title="This job is on an emergency tax code",
        explanation=_emergency_basis_explanation(extract),
        estimate=estimate,
        next_step=(
            "Check your tax code in your HMRC personal tax account, or ask "
            "your payroll team whether they have your P45 or a starter "
            "checklist."
        ),
        source_fields=source_fields,
    )
    return _RuleResult("failed", finding)


# --------------------------------------------------------------------------
# R3 — no personal allowance applied (BR, 0T, D0, D1)
# --------------------------------------------------------------------------


def _check_no_allowance(
    extract: PayslipExtract, tax_code: TaxCode, context: Optional[UserContext]
) -> _RuleResult:
    if tax_code.free_pay_annual != 0:
        return _RuleResult("passed", None)

    # 0T usually means payroll had NO tax code details at all when this
    # was run - genuinely wrong far more often than a normal second-job
    # BR/D0/D1 code, so it gets a stronger note. Only in the True/None
    # branches, though (see below): in the False branch we've just told
    # the user this looks like a normal second job, and immediately
    # following that with "but it's usually wrong" undercuts the
    # reassurance we were giving - phase 4.1 item 4.
    code_note = (
        "0T usually means payroll had no tax code details for you at all "
        "when this was run, so it's more often genuinely wrong than a "
        "typical second-job code."
        if tax_code.kind == "0T"
        else "That's a normal setup for a second job, where a different employer applies your allowance."
    )

    only_job = context.only_job if context is not None else None

    if only_job is True:
        severity = "action"
        explanation = (
            "No tax-free personal allowance is being applied to this job - "
            "every pound is taxed. You told us this is your only income, so "
            f"you're likely paying tax you don't owe. {code_note}"
        )
    elif only_job is False:
        severity = "advisory"
        explanation = (
            "No tax-free personal allowance is being applied to this job. "
            "You told us this isn't your only income, so this is what we'd "
            "expect if your allowance is applied at your main job - worth "
            "checking that it actually is."
        )
    else:
        severity = "advisory"
        explanation = (
            "No tax-free personal allowance is being applied to this job. "
            "That's correct if your allowance is being used at another job. "
            "If this is your only income, or you've left that other job, "
            f"it's worth checking. {code_note}"
        )

    finding = Finding(
        id="tax_code_no_allowance",
        severity=severity,
        title="No tax-free allowance is being applied to this job",
        explanation=explanation,
        next_step=(
            "Check your tax codes in your HMRC personal tax account, or ask "
            "your payroll team."
        ),
        source_fields=["tax_code.value"],
    )
    return _RuleResult("failed", finding)


# --------------------------------------------------------------------------
# R4 — annual income under the personal allowance but tax deducted
# --------------------------------------------------------------------------

_UNDER_ALLOWANCE_FIELDS = [
    "pay.gross_this_period",
    "pay.gross_ytd",
    "period.period_number",
    "period.frequency",
    "deductions.income_tax_ytd",
]


_UNDER_ALLOWANCE_CHECK_LABEL = "whether your income is under your tax-free allowance"


def _check_under_allowance_but_taxed(extract: PayslipExtract) -> _RuleResult:
    if not can_run(extract, _UNDER_ALLOWANCE_FIELDS):
        return _RuleResult(
            "gated", None, _gated_note(_UNDER_ALLOWANCE_CHECK_LABEL, extract, _UNDER_ALLOWANCE_FIELDS)
        )

    annualised = _safe(
        annualise,
        extract.pay.gross_this_period,
        extract.pay.gross_ytd,
        extract.period.period_number,
        extract.period.frequency,
    )
    if annualised is None:
        # annualise() is still a stub - genuinely can't tell, so this
        # counts the same as missing data: gated, not passed. No note,
        # though: this is a known, developer-side gap that would fire on
        # every single payslip right now, not something the user's own
        # payslip is missing - see the _RuleResult.note docstring.
        return _RuleResult("gated", None)

    income_tax_ytd = extract.deductions.income_tax_ytd
    personal_allowance = RATES["personal_allowance"]
    if not (annualised < personal_allowance and income_tax_ytd > 0):
        return _RuleResult("passed", None)

    finding = Finding(
        id="under_personal_allowance_but_taxed",
        severity="action",
        title="You're on track to earn under your tax-free allowance, but tax has been taken",
        explanation=(
            "If this job carries on as it is, your total pay for the tax "
            f"year looks like it will stay under the £{int(personal_allowance):,} "
            "personal allowance - the amount everyone can earn tax-free. "
            "Income tax has still been deducted from this payslip."
        ),
        estimate=Estimate(
            label="Possible overpayment",
            amount_gbp=income_tax_ytd,
        ),
        next_step=(
            "Check your HMRC personal tax account - a refund can usually be "
            "claimed for the current tax year and previous tax years too."
        ),
        source_fields=_UNDER_ALLOWANCE_FIELDS,
    )
    return _RuleResult("failed", finding)


# --------------------------------------------------------------------------
# R5 — reconciliation failure
# --------------------------------------------------------------------------


def _check_reconciliation(extract: PayslipExtract) -> _RuleResult:
    if extract.reconciles is None:
        # reconciles is computed in extraction.py from gross, net and
        # every deduction together - there's no single dotted path to
        # blame, so this note is a fixed sentence rather than built via
        # _gated_note().
        return _RuleResult(
            "gated",
            None,
            "We couldn't check whether this payslip's figures add up - "
            "gross pay, net pay or a deduction wasn't readable.",
        )
    if extract.reconciles is True:
        return _RuleResult("passed", None)

    # reconciles is only ever False here when extraction trusted every
    # component figure enough to do the sum (see extraction._reconciles) -
    # so those fields are readable and not null, safe to use directly.
    deductions = extract.deductions
    total = sum(
        (
            value
            for value in (
                deductions.income_tax,
                deductions.national_insurance,
                deductions.pension_employee,
                deductions.student_loan,
            )
            if value is not None
        ),
        Decimal("0"),
    )
    total += sum((item.amount for item in deductions.other), Decimal("0"))
    difference = (extract.pay.gross_this_period - total) - extract.net_pay

    finding = Finding(
        id="reconciliation_mismatch",
        severity="advisory",
        title="This payslip's figures don't add up",
        explanation=(
            "Gross pay, minus deductions, doesn't match net pay on this "
            f"payslip. The difference is £{abs(difference):.2f}. We can't "
            "tell you why from the numbers alone."
        ),
        next_step=(
            "Check with your payroll team - ask them to explain the gap "
            "between gross pay, deductions and net pay."
        ),
        source_fields=["reconciles"],
    )
    return _RuleResult("failed", finding)


# --------------------------------------------------------------------------
# R6 — no pension contribution
# --------------------------------------------------------------------------


def _no_pension_finding() -> Finding:
    return Finding(
        id="no_pension_contribution",
        severity="advisory",
        title="No pension contributions from you on this payslip",
        explanation=(
            "Nothing is going into a pension from your own pay on this job. "
            "Auto-enrolment applies once you're 22 or over and earning "
            "above the threshold from this employer, so this may simply "
            "mean you're not eligible yet. If you are eligible and opted "
            "out, you're also turning down whatever your employer would "
            "have added."
        ),
        next_step=(
            "Ask your employer whether you're eligible for auto-enrolment "
            "and what they'd contribute."
        ),
        source_fields=["deductions.pension_employee"],
    )


_PENSION_CHECK_LABEL = "your pension contributions"
_PENSION_FIELDS = ["deductions.pension_employee"]


def _check_pension(extract: PayslipExtract) -> _RuleResult:
    if can_run(extract, _PENSION_FIELDS):
        if extract.deductions.pension_employee == 0:
            return _RuleResult("failed", _no_pension_finding())
        return _RuleResult("passed", None)

    # Fallback: no employee figure printed at all (genuinely absent, not
    # flagged unreadable), but an employer contribution is - a pension
    # scheme clearly exists on this payslip, so the same explanation
    # applies even though can_run() gated on the missing employee figure.
    employee_absent = (
        "deductions.pension_employee" not in extract.unreadable_fields
        and extract.deductions.pension_employee is None
    )
    if employee_absent and can_run(extract, ["deductions.pension_employer"]):
        if extract.deductions.pension_employer > 0:
            return _RuleResult("failed", _no_pension_finding())

    return _RuleResult("gated", None, _gated_note(_PENSION_CHECK_LABEL, extract, _PENSION_FIELDS))


# --------------------------------------------------------------------------
# National Insurance check
# --------------------------------------------------------------------------
#
# Not one of R1-R6 in the phase 4 brief - it only ever produced a "clear"
# finding (R7) there. Promoted to its own gated _RuleResult in phase 4.1
# item 1/3: it was previously computed inline inside _clear_findings with
# no gate bookkeeping at all, so a payslip where it was silently skipped
# (missing gross, frequency, or the reported NI figure) looked identical
# to one where NI genuinely couldn't be verified - checks_run/checks_passed
# didn't know the difference, and nothing told the user why. Bringing it
# into the same _RuleResult shape as every other check fixes both.

_NI_CHECK_LABEL = "your National Insurance"
_NI_FIELDS = ["pay.gross_this_period", "deductions.national_insurance", "period.frequency"]


def _check_national_insurance(extract: PayslipExtract) -> _RuleResult:
    """
    Deliberately does NOT require deductions.national_insurance_ytd or
    deductions.ni_category: national_insurance_due() only ever takes
    gross_this_period, frequency and category (defaulting to "A") - NI is
    never cumulative, so a YTD figure is not part of the calculation at
    all, and ni_category is read directly with a safe "A" default rather
    than gated, since a missing category on a real payslip almost always
    means the standard category. Requiring either would gate this check
    out for reasons the calculation itself doesn't care about.
    """
    if not can_run(extract, _NI_FIELDS):
        return _RuleResult("gated", None, _gated_note(_NI_CHECK_LABEL, extract, _NI_FIELDS))

    category = extract.deductions.ni_category or "A"
    expected_ni = _safe(
        national_insurance_due, extract.pay.gross_this_period, extract.period.frequency, category
    )
    if expected_ni is None:
        # category outside MVP scope (anything but "A") - a scope gap,
        # not a data-readability one, so no user-facing note; same
        # reasoning as the stub-calculation case in
        # _check_under_allowance_but_taxed.
        return _RuleResult("gated", None)

    if expected_ni == extract.deductions.national_insurance:
        finding = Finding(
            id="ni_looks_right",
            severity="clear",
            title="National Insurance looks right",
            explanation=(
                "The National Insurance deducted on this payslip matches "
                "what we'd expect for your pay."
            ),
            source_fields=_NI_FIELDS,
        )
        return _RuleResult("passed", finding)

    # Mismatch: the check ran and something looks off, but phase 4 never
    # defined a finding for "NI looks wrong" - that's a deliberate scope
    # limit, not an oversight, so this deliberately produces no finding.
    # It still counts as run-but-not-passed rather than silently passing.
    return _RuleResult("failed", None)


# --------------------------------------------------------------------------
# R7 — clear findings
# --------------------------------------------------------------------------


def _clear_findings(
    extract: PayslipExtract,
    tax_code: Optional[TaxCode],
    r2_fired: bool,
    r3_fired: bool,
) -> list[Finding]:
    """
    An MOT that only ever complains is a nag - these are what make it a
    verdict. Capped at three (_MAX_CLEAR_FINDINGS) so they never crowd out
    the real findings. Deliberately narrower than the full rule set:
    pension has no "clear" version here, only ever a finding or silence,
    per the brief. National Insurance's clear finding is built by
    _check_national_insurance instead of here - see that function.
    """
    clears: list[Finding] = []

    if tax_code is not None and not r2_fired and not r3_fired:
        clears.append(
            Finding(
                id="tax_code_looks_right",
                severity="clear",
                title="Your tax code looks right",
                explanation=(
                    "Your tax code is cumulative and applies a tax-free "
                    "allowance, which is what we'd expect to see."
                ),
                source_fields=["tax_code.value"],
            )
        )

    if extract.reconciles is True:
        clears.append(
            Finding(
                id="figures_reconcile",
                severity="clear",
                title="The figures on this payslip add up",
                explanation="Gross pay, minus deductions, matches net pay to the penny.",
                source_fields=["reconciles"],
            )
        )

    return clears[:_MAX_CLEAR_FINDINGS]


# --------------------------------------------------------------------------
# Verdict, ordering and score
# --------------------------------------------------------------------------


def _order_and_cap(findings: list[Finding]) -> list[Finding]:
    """Action first, then advisory, then clear. Within a severity, higher
    estimated amount first (no estimate sorts last within its severity).
    Non-clear capped at four, clear capped at three."""

    def sort_key(finding: Finding):
        amount = finding.estimate.amount_gbp if finding.estimate else Decimal("-1")
        return (_SEVERITY_ORDER[finding.severity], -amount)

    non_clear = sorted((f for f in findings if f.severity != "clear"), key=sort_key)
    clear = [f for f in findings if f.severity == "clear"]
    return non_clear[:_MAX_SURFACED_FINDINGS] + clear[:_MAX_CLEAR_FINDINGS]


def _build_verdict(findings: list[Finding]) -> Verdict:
    non_clear = [f for f in findings if f.severity != "clear"]
    if not non_clear:
        return Verdict(headline="This payslip looks fine to us", severity="clear")

    count = len(non_clear)
    noun = "thing" if count == 1 else "things"
    severity = "action" if any(f.severity == "action" for f in non_clear) else "advisory"
    return Verdict(headline=f"{count} {noun} worth checking on this payslip", severity=severity)


_MOVER_TEXT = {
    "tax_code_unreadable": "Uploading a clearer copy of this payslip so we can check your tax code",
    "tax_code_unparseable": "Checking your tax code against your HMRC personal tax account",
    "tax_code_emergency_basis": "Getting your tax code corrected off the emergency basis",
    "tax_code_no_allowance": "Checking whether your allowance is being used at another job",
    "under_personal_allowance_but_taxed": "Claiming back the income tax you've paid so far",
    "reconciliation_mismatch": "Getting payroll to explain the figures that don't add up",
    "no_pension_contribution": "Checking whether you're eligible for a workplace pension",
}


def _build_score(
    findings: list[Finding],
    checks_run: int,
    checks_passed: int,
    gated_notes: list[str],
) -> Score:
    """
    Explainable, not clever: start at 100, subtract a fixed weight per
    non-clear finding actually surfaced (action heavier than advisory) so
    the score never implies more than the findings list in front of the
    user shows.

    contract.py's Score has no field for "checks gated out" (phase 4.1
    item 3 asked to surface this without changing the contract), so a
    gated check's plain-English reason - "we couldn't check X because Y
    wasn't readable" - rides along in movers, after the ordinary
    what-would-improve-your-score entries. It's not a fix the user can
    action the same way the others are, but it tells them what we did NOT
    check rather than quietly omitting it, which is the point.
    """
    non_clear = [f for f in findings if f.severity != "clear"]
    weight = sum(_SEVERITY_WEIGHT[f.severity] for f in non_clear)
    value = max(0, 100 - weight)

    movers: list[str] = []
    for finding in non_clear:
        text = _MOVER_TEXT.get(finding.id)
        if text and text not in movers:
            movers.append(text)
    for note in gated_notes:
        if note not in movers:
            movers.append(note)

    return Score(
        value=value,
        checks_passed=checks_passed,
        checks_run=checks_run,
        movers=movers[:_MAX_MOVERS],
    )


# --------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------

_PROJECTION_FIELDS = ["pay.gross_this_period", "period.period_number", "period.frequency"]


def _build_projections(
    extract: PayslipExtract, tax_code: Optional[TaxCode], r2_fired: bool
) -> list[Projection]:
    """Only emergency_code_full_year, per the brief. Skipped entirely
    (never an unqualified/partial projection) unless R2 actually fired and
    income_tax_due() is available."""
    if not r2_fired or tax_code is None or not can_run(extract, _PROJECTION_FIELDS):
        return []

    frequency = extract.period.frequency
    period_number = extract.period.period_number
    gross_per_period = extract.pay.gross_this_period
    total_periods = periods_in_year(frequency)

    non_cum_period_tax = _safe(
        income_tax_due,
        PayPeriodFacts(
            gross_this_period=gross_per_period,
            gross_ytd=gross_per_period,  # non-cumulative ignores YTD entirely
            tax_code=tax_code,
            period_number=period_number,
            frequency=frequency,
        ),
    )
    if non_cum_period_tax is None:
        return []  # income_tax_due() is still a stub

    cumulative_code = _as_cumulative(tax_code)

    def path_a(period: int) -> Decimal:
        return (non_cum_period_tax * period).quantize(Decimal("0.01"))

    def path_b(period: int) -> Decimal:
        result = _safe(_cumulative_tax_to_date, cumulative_code, gross_per_period, period, frequency)
        return result if result is not None else Decimal("0.00")

    midpoint = min(total_periods, period_number + max(1, (total_periods - period_number) // 2))
    # A dict, keyed by period, de-dupes automatically when period_number,
    # midpoint and total_periods collide near the end of the tax year -
    # better to show fewer points than a repeated one.
    labelled_periods = {
        period_number: f"Now (period {period_number})",
        midpoint: f"Period {midpoint}",
        total_periods: "End of tax year",
    }
    points = [
        ProjectionPoint(label=label, path_a=path_a(period), path_b=path_b(period))
        for period, label in sorted(labelled_periods.items())
    ]

    unit = "a month" if frequency == "monthly" else "a week"
    return [
        Projection(
            key="emergency_code_full_year",
            title="What staying on the emergency code costs over the tax year",
            path_a_label="If the code stays as it is",
            path_b_label="If it's corrected to a normal cumulative code",
            points=points,
            caveat=(
                f"Assumes you keep earning about £{gross_per_period:,.2f} {unit} "
                "for the rest of the tax year, and that nothing else about "
                "your tax code changes. Figures are estimates."
            ),
        )
    ]


# --------------------------------------------------------------------------
# Check orchestration
# --------------------------------------------------------------------------

# Every rule that isn't R1 (which always runs) or R2/R3 (which only run
# once R1 has produced a tax_code), in a fixed, documented order - the
# same list both analyse() and gate_report() below evaluate.
_UNCONDITIONAL_CHECKS: list[tuple[str, Callable[[PayslipExtract], _RuleResult]]] = [
    ("under_personal_allowance_but_taxed", _check_under_allowance_but_taxed),
    ("reconciliation", _check_reconciliation),
    ("pension", _check_pension),
    ("national_insurance", _check_national_insurance),
]


def _evaluate_checks(
    extract: PayslipExtract, context: Optional[UserContext]
) -> tuple[list[tuple[str, _RuleResult]], Optional[TaxCode], bool, bool]:
    """
    Runs every check exactly once and returns its (id, _RuleResult) pair
    alongside the parsed tax_code and whether R2/R3 fired - the shared
    core behind both analyse() (which tallies these into findings/score)
    and gate_report() (which just shows what happened). Keeping this in
    one place means the two can never drift apart on what "ran" means.
    """
    results: list[tuple[str, _RuleResult]] = []

    r1_result, tax_code = _check_tax_code_readable(extract)
    results.append(("tax_code_readable", r1_result))

    r2_fired = r3_fired = False
    if tax_code is not None:
        r2_result = _check_emergency_basis(extract, tax_code)
        results.append(("tax_code_emergency_basis", r2_result))
        r2_fired = r2_result.outcome == "failed"

        r3_result = _check_no_allowance(extract, tax_code, context)
        results.append(("tax_code_no_allowance", r3_result))
        r3_fired = r3_result.outcome == "failed"

    for check_id, check_fn in _UNCONDITIONAL_CHECKS:
        results.append((check_id, check_fn(extract)))

    return results, tax_code, r2_fired, r3_fired


def gate_report(
    extract: PayslipExtract, context: Optional[UserContext] = None
) -> list[dict]:
    """
    Debug/introspection helper - not part of the wire contract, so
    contract.py doesn't need a field for it. Returns every check's id,
    outcome ("gated" / "passed" / "failed") and, for a gated check caused
    by an unreadable field, the reason - so a caller like
    tools/try_analysis.py can show exactly which rules ran and which
    field caused a gate, rather than inferring it from a finding's
    absence. See phase 4.1 item 2.
    """
    results, _tax_code, _r2, _r3 = _evaluate_checks(extract, context)
    return [
        {"id": check_id, "outcome": result.outcome, "note": result.note}
        for check_id, result in results
    ]


# --------------------------------------------------------------------------
# Public interface
# --------------------------------------------------------------------------


def analyse(
    extracts: list[PayslipExtract],
    context: Optional[UserContext] = None,
) -> AnalysisResult:
    """
    extracts is a list to support multi-job later. Only the first is
    analysed for now; a second or later entry adds a warning rather than
    attempting any cross-payslip logic.
    """
    if not extracts:
        return AnalysisResult(
            status="unreadable",
            failure_reason="No payslip was extracted to analyse.",
        )

    extract = extracts[0]
    if len(extracts) > 1:
        extract = extract.model_copy(
            update={"warnings": [*extract.warnings, _MULTI_JOB_WARNING]}
        )

    check_results, tax_code, r2_fired, r3_fired = _evaluate_checks(extract, context)

    findings: list[Finding] = []
    checks_run = 0
    checks_passed = 0
    gated_notes: list[str] = []

    for _check_id, result in check_results:
        if result.finding is not None:
            findings.append(result.finding)
        if result.outcome == "gated":
            if result.note:
                gated_notes.append(result.note)
            continue
        checks_run += 1
        if result.outcome == "passed":
            checks_passed += 1

    findings.extend(_clear_findings(extract, tax_code, r2_fired, r3_fired))

    ordered = _order_and_cap(findings)
    verdict = _build_verdict(ordered)
    score = _build_score(ordered, checks_run, checks_passed, gated_notes)
    projections = _build_projections(extract, tax_code, r2_fired)

    return AnalysisResult(
        status="ok",
        extract=extract,
        verdict=verdict,
        findings=ordered,
        projections=projections,
        score=score,
    )
