"""
Shared types for the Slyp tax engine.

Both halves of the engine import from this file:

  - the calculation layer (Ayaan) works out what someone SHOULD be paying
  - the findings layer (Kelvin) decides what we TELL the user about it

Nothing in here touches a payslip, a file, an API or the frontend.

Money rule: use Decimal everywhere, never float. Round to 2dp at the very
end of a calculation, never in the middle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Optional


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class UnsupportedPayslip(Exception):
    """
    Raised when a payslip falls outside what the MVP supports.

    We raise instead of guessing. A wrong number on someone's payslip is
    worse than telling them we don't support their situation yet.

    Examples: Scottish or Welsh band calculations, salary sacrifice,
    benefits in kind, statutory pay, directors' NI, NI categories other
    than A, income above £100,000 (allowance taper), unparseable tax codes.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# --------------------------------------------------------------------------
# Literals
# --------------------------------------------------------------------------

Frequency = Literal["monthly", "weekly"]

TaxCodeKind = Literal[
    "standard",  # e.g. 1257L - has a personal allowance
    "BR",        # basic rate on everything, no allowance
    "D0",        # higher rate on everything, no allowance
    "D1",        # additional rate on everything, no allowance
    "0T",        # no allowance, normal bands
    "K",         # negative allowance (amount ADDED to taxable pay)
    "NT",        # no tax - out of scope for MVP
]

Region = Literal["UK", "S", "C"]  # UK = England/NI, S = Scotland, C = Wales

StudentLoanPlan = Literal["1", "2", "4", "5", "PG"]


# --------------------------------------------------------------------------
# Tax code
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TaxCode:
    """
    A parsed UK tax code.

    Produced by parse_tax_code(). Consumed by income_tax_due() and by the
    findings layer when deciding whether a code looks right for someone.

    free_pay_annual is the whole point of this object: it is how much
    tax-free pay the code grants over a full tax year.
        1257L -> Decimal("12570")
        BR    -> Decimal("0")
        0T    -> Decimal("0")
        K475  -> Decimal("-4750")   negative: added to taxable pay

    cumulative is False for W1, M1 and X suffixes. Non-cumulative means
    each pay period is taxed on its own, ignoring the rest of the year.
    That is the emergency basis, and it is usually why someone overpays.
    """

    raw: str
    kind: TaxCodeKind
    free_pay_annual: Decimal
    cumulative: bool
    region: Region = "UK"

    @property
    def is_emergency_basis(self) -> bool:
        """True when the code is applied on a week 1 / month 1 basis."""
        return not self.cumulative

    @property
    def grants_allowance(self) -> bool:
        """True when this code gives the person any tax-free pay."""
        return self.free_pay_annual > 0


# --------------------------------------------------------------------------
# Pay breakdown
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PayBreakdown:
    """
    What SHOULD be deducted for one pay period, given a set of facts.

    Returned by the what-if projection, and used by the findings layer to
    compare against what a payslip actually shows.

    All figures are for a single pay period, not the year.
    """

    gross: Decimal
    income_tax: Decimal
    national_insurance: Decimal
    student_loan: Decimal = Decimal("0")
    pension_employee: Decimal = Decimal("0")

    @property
    def total_deductions(self) -> Decimal:
        return (
            self.income_tax
            + self.national_insurance
            + self.student_loan
            + self.pension_employee
        )

    @property
    def net(self) -> Decimal:
        return self.gross - self.total_deductions


# --------------------------------------------------------------------------
# Inputs to the calculation layer
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PayPeriodFacts:
    """
    Everything the calculation layer needs to know about one pay period.

    This is the input object. It contains only numbers taken off a payslip
    plus where we are in the tax year. It deliberately contains no personal
    details, no employer, no dates beyond the period number.

    period_number is 1-12 for monthly pay, 1-52 for weekly.
    gross_ytd INCLUDES this period.
    """

    gross_this_period: Decimal
    gross_ytd: Decimal
    tax_code: TaxCode
    period_number: int
    frequency: Frequency
    ni_category: str = "A"
    student_loan_plan: Optional[StudentLoanPlan] = None

    def __post_init__(self) -> None:
        periods = 12 if self.frequency == "monthly" else 52
        if not 1 <= self.period_number <= periods:
            raise ValueError(
                f"period_number {self.period_number} out of range for "
                f"{self.frequency} pay (expected 1-{periods})"
            )
        if self.gross_ytd < self.gross_this_period:
            raise ValueError("gross_ytd must include this period's gross pay")


# --------------------------------------------------------------------------
# Helpers both halves need
# --------------------------------------------------------------------------

def periods_in_year(frequency: Frequency) -> int:
    """Number of pay periods in a tax year for a given pay frequency."""
    return 12 if frequency == "monthly" else 52


def to_money(value) -> Decimal:
    """
    Convert to Decimal for money handling.

    Always build Decimals from strings or ints, never from floats, or you
    inherit binary rounding errors: Decimal(0.1) is not 0.1.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
