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

from pydantic import BaseModel, Field


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
    value: int = Field(ge=0, le=100)
    checks_passed: int
    checks_run: int
    movers: list[str] = Field(
        default_factory=list, description="What would move it, plain English"
    )


class Verdict(BaseModel):
    """The MOT headline: what the check-up concluded."""

    headline: str = Field(description='e.g. "2 things to check on this payslip"')
    severity: Severity


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

    is_example_data: bool = Field(
        False, description="True for /api/mock/scan so the UI can label it"
    )
