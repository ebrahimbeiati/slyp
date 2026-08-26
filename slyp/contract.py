"""
Slyp JSON contract  —  v1

The wire format between the backend and the frontend, and the shape that
extraction produces.

Three objects:

    PayslipExtract   what the payslip ACTUALLY SAYS      (from extraction)
    Finding          what we TELL THE USER about it      (from the findings layer)
    AnalysisResult   the whole response the frontend renders

Not to be confused with slyp/types.py, which holds the internal objects the
two halves of the tax engine pass between themselves. This file is what
leaves the backend.

Design rules:

  1. Every extracted field is optional. A missing field is fine, a wrong
     field is not. If extraction is not confident, the field is null and
     its name goes in unreadable_fields.

  2. The model fills this in. It never fills in a Finding, an estimate or
     a score. Code calculates, AI explains.

  3. Nothing personal survives extraction. No name, address, NI number or
     employee number appears anywhere in this contract. The frontend holds
     the user's name locally and never sends it.

This is v1. It will change once real payslips hit it. Version it, change
it deliberately, tell the others when it moves.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field


Frequency = Literal["monthly", "weekly"]
Severity = Literal["clear", "advisory", "action"]


# ==========================================================================
# PayslipExtract  —  produced by extraction, consumed by the findings layer
# ==========================================================================

class Period(BaseModel):
    pay_date: Optional[date] = None
    period_number: Optional[int] = Field(
        None, description="1-12 for monthly pay, 1-52 for weekly"
    )
    frequency: Optional[Frequency] = None
    tax_year: Optional[str] = Field(None, description='e.g. "2026/27"')


class TaxCodeRead(BaseModel):
    """
    The tax code exactly as printed. Not parsed, not interpreted —
    parsing is the tax engine's job.
    """

    value: Optional[str] = Field(None, description='e.g. "1257L", "BR", "1257L W1"')


class Pay(BaseModel):
    hourly_rate: Optional[Decimal] = None
    hours: Optional[Decimal] = None
    gross_this_period: Optional[Decimal] = None
    gross_ytd: Optional[Decimal] = Field(
        None, description="Year to date INCLUDING this period"
    )


class OtherDeduction(BaseModel):
    """
    Anything that is not tax, NI, pension or student loan.

    IMPORTANT: keep the amount and a generic type only. Never carry the
    raw label through. Some deduction lines are special category data
    under UK GDPR (trade union subs reveal union membership) or sensitive
    by implication (attachment of earnings orders, childcare vouchers).
    """

    type: Literal["union", "court_order", "charity", "loan", "other"] = "other"
    amount: Decimal


class Deductions(BaseModel):
    income_tax: Optional[Decimal] = None
    income_tax_ytd: Optional[Decimal] = None
    national_insurance: Optional[Decimal] = None
    national_insurance_ytd: Optional[Decimal] = None
    ni_category: Optional[str] = None
    pension_employee: Optional[Decimal] = None
    pension_employer: Optional[Decimal] = None
    pension_percent: Optional[Decimal] = None
    student_loan: Optional[Decimal] = None
    student_loan_plan: Optional[Literal["1", "2", "4", "5", "PG"]] = None
    other: list[OtherDeduction] = Field(default_factory=list)


class Source(BaseModel):
    filename: Optional[str] = None
    pages: Optional[int] = None
    scanned_at: datetime


# ==========================================================================
# Field labels
# ==========================================================================
#
# The one place a dotted field path becomes words a person can read.
#
# Paths are an internal key: the findings layer matches Finding.source_fields
# against unreadable_fields, and both have to be exact. They are not English,
# and "tax_code.value" reached a real user's screen because three separate
# places rendered the key instead of a label.
#
# Deliberately in Python rather than the frontend. failure_reason is built
# server-side (analysis.validate_extract), so a TypeScript copy would have
# to agree with this one forever, and would not.

FIELD_LABELS: dict[str, str] = {
    "employer_name": "your employer's name",
    "period.pay_date": "your pay date",
    "period.period_number": "the pay period number",
    "period.frequency": "how often you are paid",
    "period.tax_year": "the tax year",
    "tax_code.value": "your tax code",
    "pay.hourly_rate": "your hourly rate",
    "pay.hours": "your hours",
    "pay.gross_this_period": "your gross pay",
    "pay.gross_ytd": "your gross pay so far this year",
    "deductions.income_tax": "your income tax",
    "deductions.income_tax_ytd": "your income tax so far this year",
    "deductions.national_insurance": "your National Insurance",
    "deductions.national_insurance_ytd": "your National Insurance so far this year",
    "deductions.ni_category": "your National Insurance category",
    "deductions.pension_employee": "your pension contribution",
    "deductions.pension_employer": "your employer's pension contribution",
    "deductions.pension_percent": "your pension percentage",
    "deductions.student_loan": "your student loan deduction",
    "deductions.student_loan_plan": "your student loan plan",
    "net_pay": "your net pay",
}


def field_label(path: str) -> str:
    """A dotted path as words. Falls back to something generic rather than
    leaking the path, because a path this map has not learned yet is
    exactly when the leak would happen."""
    return FIELD_LABELS.get(path, "one of the figures on your payslip")


def field_labels(paths: list[str]) -> list[str]:
    """Labels for a list of paths, in order, without duplicates - two
    unreadable year-to-date fields should not say the same thing twice."""
    seen: dict[str, None] = {}
    for path in paths:
        seen.setdefault(field_label(path), None)
    return list(seen)


class PayslipExtract(BaseModel):
    """What the payslip actually says. No judgements, no calculations."""

    source: Source
    employer_name: Optional[str] = Field(
        None,
        description="Kept for labelling multiple jobs. Never sent to the model.",
    )
    period: Period = Field(default_factory=Period)
    tax_code: TaxCodeRead = Field(default_factory=TaxCodeRead)
    pay: Pay = Field(default_factory=Pay)
    deductions: Deductions = Field(default_factory=Deductions)
    net_pay: Optional[Decimal] = None

    confidence: dict[str, float] = Field(
        default_factory=dict,
        description=(
            'Per-field, 0-1, keyed by dotted path: {"tax_code.value": 0.98}. '
            "Model self-reported confidence is a signal, not a measurement — "
            "always back it with the arithmetic checks below."
        ),
    )
    unreadable_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Dotted paths we could not read confidently. The findings layer "
            "must not run a rule that depends on a field listed here."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Things worth noting that are not findings, in plain English.",
    )
    reconciles: Optional[bool] = Field(
        None,
        description=(
            "gross - all deductions == net, to the penny. Computed in code, "
            "not by the model. False means treat every figure as suspect."
        ),
    )
    @computed_field  # type: ignore[prop-decorator]
    @property
    def unreadable_field_labels(self) -> list[str]:
        """unreadable_fields as words, for anything that displays them.

        A computed field rather than a stored one, so it is derived from
        unreadable_fields on every serialisation and cannot drift out of
        step with it - including on a hand-built PayslipExtract, which is
        how most of the test suite constructs one.

        The frontend renders THIS. unreadable_fields stays as paths
        because the findings layer matches on them.
        """
        return field_labels(self.unreadable_fields)

    previous_employment_ytd_present: bool = Field(
        False,
        description=(
            "The payslip shows a previous-employment year-to-date line — a "
            "P45 carry-forward from an earlier job this tax year. Detected "
            "in code from the document's own labels, not asked of the "
            "model. When true, this employment's YTD figures are not the "
            "whole year, which suppresses the allowance-used figure "
            "regardless of what the user answered about other employment."
        ),
    )


# ==========================================================================
# UserContext  —  the one question we ask, session only
# ==========================================================================

class UserContext(BaseModel):
    """
    A single payslip cannot tell us whether someone's personal allowance is
    being used at another job. So we ask. One tap, no account, never stored.

    null means unanswered — findings that depend on it stay conditional.
    """

    only_job: Optional[bool] = None


# ==========================================================================
# Finding  —  produced by the findings layer
# ==========================================================================

class Estimate(BaseModel):
    label: str = Field(description='e.g. "Possible overpayment so far this year"')
    amount_gbp: Decimal
    is_estimate: bool = True


class Finding(BaseModel):
    """
    One thing we tell the user. Always computed by code. The model may
    rewrite explanation into friendlier prose, but never produces a number,
    a severity or a next step.
    """

    id: str = Field(description='Stable key, e.g. "tax_code_br_allowance_elsewhere"')
    severity: Severity
    title: str = Field(description='Short, plain. e.g. "This job is on a BR code"')
    explanation: str = Field(
        description=(
            "Plain English, conditional where we cannot be certain. "
            'e.g. "That is right if your allowance is used at another job. '
            'If this is your only income, it is worth checking."'
        )
    )
    estimate: Optional[Estimate] = None
    next_step: Optional[str] = Field(
        None,
        description=(
            "What to do, pointing at HMRC or payroll. Never a product "
            "recommendation — guidance, not regulated advice."
        ),
    )
    projection_key: Optional[str] = Field(
        None, description="Fast-forward this finding maps to, or null"
    )
    source_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Extract fields this finding depends on. If any appear in "
            "unreadable_fields, the rule must not run."
        ),
    )


# ==========================================================================
# Projection  —  the fast-forward
# ==========================================================================

class ProjectionPoint(BaseModel):
    label: str = Field(description='e.g. "Age 30", "End of tax year"')
    path_a: Decimal
    path_b: Decimal


class Projection(BaseModel):
    """
    Two futures compared, computed deterministically from the person's own
    numbers. Never generated by the model.
    """

    key: str
    title: str
    path_a_label: str = Field(description='e.g. "If nothing changes"')
    path_b_label: str = Field(description='e.g. "If you fix it"')
    unit: Literal["gbp"] = "gbp"
    points: list[ProjectionPoint]
    caveat: str = Field(
        description="What this assumes, in plain English. Always populated."
    )


# ==========================================================================
# AnalysisResult  —  the response the frontend renders
# ==========================================================================

class Score(BaseModel):
    # None when no check applied - deliberately not 0, which would read as
    # a failing payslip rather than an unscored one. See
    # analysis.build_score().
    value: Optional[int] = Field(default=None, ge=0, le=100)
    checks_passed: int
    checks_run: int
    movers: list[str] = Field(
        default_factory=list, description="What would move it, plain English"
    )
    not_applicable: list[str] = Field(
        default_factory=list,
        description=(
            "Plain-English reasons a check did not apply to this payslip. "
            "These are NOT failures and NOT passes - they are checks with "
            "nothing to check, and they are excluded from checks_run so "
            "the score never counts a vacuous comparison as confidence."
        ),
    )


class Verdict(BaseModel):
    """The MOT headline: what the check-up concluded."""

    headline: str = Field(description='e.g. "2 things to check on this payslip"')
    severity: Severity


class AllowanceUsage(BaseModel):
    """
    How much of the annual Personal Allowance this employment's pay has
    used so far this tax year.

    Arithmetic on figures the payslip itself carries: year-to-date gross
    against the allowance the tax code grants. Not a projection, and
    nothing here says anything about what happens by April.

    Populated ONLY when the user has confirmed they have had no other
    employment this tax year, and suppressed entirely otherwise — see
    analysis.build_allowance_usage() for the full set of guards. Year-to-
    date figures cover this employment only, so for anyone with a previous
    employer this would be understated by whatever they earned there, and
    a remaining-allowance number reads as a fact rather than an estimate.
    That is a stricter bar than the emergency-code overpayment estimate
    clears, deliberately: that one is framed as "possible, check with
    HMRC", and this one would be acted on.

    There is deliberately no `remaining_gbp` field. The difference is one
    subtraction away, but a field with that name is an invitation to
    render "you have £5,070 left to earn tax-free" — which is a statement
    about future earnings, i.e. the projection this whole object avoids
    being. `statement` is the sentence to show.
    """

    used_gbp: Decimal = Field(
        description=(
            "Year-to-date gross, capped at the annual allowance — you "
            "cannot use more allowance than you have."
        )
    )
    allowance_gbp: Decimal = Field(
        description="Annual allowance the tax code grants, e.g. 12570 for 1257L."
    )
    statement: str = Field(
        description=(
            "The bounded sentence to display. Written here rather than in "
            "the frontend so there is one place the wording can be checked."
        )
    )


class Explanation(BaseModel):
    """
    What something printed on the payslip MEANS. Not a judgement about it.

    The distinction is the whole point. A Finding says something about the
    user's situation and is gated on what we know about it; an Explanation
    says what a code does, which is true regardless of whose payslip it is
    and needs no gate beyond "we read the value confidently".

    That line is easy to cross and the BR code is where it would happen:
    "no personal allowance is applied here" is an explanation, and "which
    is normal for a second job" is a claim about the user's circumstances
    that the findings layer only makes when user_context.only_job is False.
    Nothing in here may say a code is normal, expected or correct.

    `subject` is deliberately narrow. NI category and student loan plan
    were scoped and left out - the first needs its 14 categories checked
    against HMRC before we describe any of them, the second is null on
    every fixture we have and would ship unexercised. The literal widens
    when they are built, rather than advertising subjects nothing produces.
    """

    subject: Literal["tax_code"]
    heading: str = Field(description='Short, e.g. "What your tax code means"')
    body: str = Field(description="Plain English, no judgement, no advice.")


class AnalysisResult(BaseModel):
    status: Literal["ok", "unreadable", "not_a_payslip", "unsupported"] = "ok"
    failure_reason: Optional[str] = Field(
        None,
        description=(
            "Populated when status is not ok. Plain English, says what went "
            "wrong and what to do. We fail loudly rather than guessing."
        ),
    )

    extract: Optional[PayslipExtract] = None
    verdict: Optional[Verdict] = None
    findings: list[Finding] = Field(default_factory=list)
    projections: list[Projection] = Field(default_factory=list)
    score: Optional[Score] = None
    explanations: list[Explanation] = Field(
        default_factory=list,
        description=(
            "What the payslip's own codes mean, in plain English. Empty "
            "when nothing could be explained confidently, or when a finding "
            "already explains the same thing - see "
            "analysis.build_tax_code_explanation()."
        ),
    )
    allowance_usage: Optional[AllowanceUsage] = Field(
        None,
        description=(
            "Personal Allowance used to date, or null when any guard "
            "suppresses it. Null is the default and the common case; the "
            "frontend renders this field or nothing, and never derives it."
        ),
    )

    is_example_data: bool = Field(
        False, description="True for /api/mock/scan so the UI can label it"
    )
