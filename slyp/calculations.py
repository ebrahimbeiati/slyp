"""
Calculation layer — OWNER: Ayaan

Works out what someone SHOULD be paying, given the numbers off a payslip.
Pure functions: same inputs always give the same output. No files, no
network, no AI, no payslips.


  Income tax:    https://www.gov.uk/income-tax-rates
  NI thresholds: https://www.gov.uk/guidance/rates-and-thresholds-for-employers
  Student loans: https://www.gov.uk/repaying-your-student-loan/what-you-pay
  Tax codes:     https://www.gov.uk/tax-codes

Scope for the MVP: England/Northern Ireland rates, weekly and monthly pay,
codes 1257L / BR / D0 / 0T / K (with optional S or C prefix), NI category A,
student loan plans 1, 2, 4, 5 and PG. Anything else raises UnsupportedPayslip.
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_DOWN

from .types import (
    Frequency,
    PayBreakdown,
    PayPeriodFacts,
    StudentLoanPlan,
    TaxCode,
    UnsupportedPayslip,
    periods_in_year,
    to_money,
)


# --------------------------------------------------------------------------
# Rates and thresholds — GOV.UK 2026/27
# --------------------------------------------------------------------------

RATES = {
    "personal_allowance": Decimal("12570"),
    "basic_rate": Decimal("0.20"),
    "basic_rate_limit": Decimal("37700"),      # taxable pay above allowance
    "higher_rate": Decimal("0.40"),
    "higher_rate_limit": Decimal("125140"),    # total income
    "additional_rate": Decimal("0.45"),
    "allowance_taper_threshold": Decimal("100000"),

    "ni": {
        "monthly": {
            "primary_threshold": Decimal("1048"),
            "upper_earnings_limit": Decimal("4189"),
        },
        "weekly": {
            "primary_threshold": Decimal("242"),
            "upper_earnings_limit": Decimal("967"),
        },
        "main_rate": Decimal("0.08"),
        "upper_rate": Decimal("0.02"),
    },

    "student_loans": {
        # annual thresholds; divide by periods in year
        "1": {"threshold": Decimal("26900"), "rate": Decimal("0.09")},
        "2": {"threshold": Decimal("29385"), "rate": Decimal("0.09")},
        "4": {"threshold": Decimal("33795"), "rate": Decimal("0.09")},
        "5": {"threshold": Decimal("25000"), "rate": Decimal("0.09")},
        "PG": {"threshold": Decimal("21000"), "rate": Decimal("0.06")},
    },
}


# --------------------------------------------------------------------------
# 1. Tax code parsing
# --------------------------------------------------------------------------

def parse_tax_code(code: str) -> TaxCode:
    """
    Parse a tax code as printed on a payslip into a TaxCode object.

    Handles: "1257L", "1257L W1", "1257L M1", "1257LX", "BR", "D0", "D1",
    "0T", "K475", and an optional leading "S" (Scotland) or "C" (Wales).
    Case and spacing vary between payroll systems, so normalise first.

    The number in a standard code is the annual allowance divided by 10:
        1257L -> free_pay_annual = 12570

    A K code is the reverse. K475 means £4,750 is ADDED to taxable pay,
    so return free_pay_annual = -4750.

    W1, M1 and X all mean the same thing: non-cumulative. Set
    cumulative=False. Everything else is cumulative.

    Raise UnsupportedPayslip for "NT" and for anything unparseable.
    """
    raw = code.strip().upper()
    compact = "".join(raw.split())

    # Normal tax codes are cumulative unless they use W1, M1 or X
    cumulative = True

    for suffix in ("W1", "M1", "X"):
        if compact.endswith(suffix):
            cumulative = False
            compact = compact[:-len(suffix)]
            break

    # Default region is England / Northern Ireland
    region = "UK"

    # Record Scottish or Welsh prefix
    if compact.startswith(("S", "C")):
        region = compact[0]
        compact = compact[1:]

    # NT is outside the MVP
    if compact == "NT":
        raise UnsupportedPayslip("NT tax codes are outside the MVP scope")

    # BR, D0, D1 and 0T give no personal allowance
    if compact in {"BR", "D0", "D1", "0T"}:
        return TaxCode(
            raw=raw,
            kind=compact,
            free_pay_annual=Decimal("0"),
            cumulative=cumulative,
            region=region,
        )

    # K code: e.g. K475 means a negative £4,750 allowance
    k_match = re.fullmatch(r"K(\d+)", compact)

    if k_match:
        return TaxCode(
            raw=raw,
            kind="K",
            free_pay_annual=-(Decimal(k_match.group(1)) * Decimal("10")),
            cumulative=cumulative,
            region=region,
        )

    # Standard code: e.g. 1257L means £12,570 allowance
    standard_match = re.fullmatch(r"(\d+)L", compact)

    if standard_match:
        return TaxCode(
            raw=raw,
            kind="standard",
            free_pay_annual=Decimal(standard_match.group(1)) * Decimal("10"),
            cumulative=cumulative,
            region=region,
        )

    # Anything we don't understand is outside the MVP
    raise UnsupportedPayslip(
        f"Unsupported or unparseable tax code: {raw}"
    )


# --------------------------------------------------------------------------
# 2. Income tax
# --------------------------------------------------------------------------

def income_tax_due(facts: PayPeriodFacts) -> Decimal:
    """
    Income tax that should be deducted THIS PERIOD.

    Two different calculations depending on the code's basis.

    CUMULATIVE (the normal case):
      1. Allowance available so far this year
             = free_pay_annual * period_number / periods_in_year
      2. Taxable pay so far  = gross_ytd - allowance so far
      3. Apply the bands to that figure -> total tax due for the year to date
      4. This period's tax = tax due to date - tax already paid in earlier
         periods. Earlier tax is not passed in, so derive it by running the
         same calculation for period_number - 1 with the year-to-date gross
         at that point (gross_ytd - gross_this_period).

    NON-CUMULATIVE (W1/M1/X):
      Ignore the year to date entirely. Give one period's worth of
      allowance and one period's worth of each band, and tax this
      period's gross on its own.

    Never return a negative figure: if the calculation comes out below
    zero (a refund is due) return Decimal("0"). The findings layer deals
    with refunds, not the calculator.

    Raise UnsupportedPayslip if annualised income is above the allowance
    taper threshold, or if the code region is not "UK".
    """
    raise NotImplementedError


# --------------------------------------------------------------------------
# 3. National Insurance
# --------------------------------------------------------------------------

def national_insurance_due(
    gross_this_period: Decimal,
    frequency: Frequency,
    category: str = "A",
) -> Decimal:
    """
    Employee National Insurance for THIS PERIOD.

    NI is never cumulative. Every pay period is worked out on its own,
    which is why there is no year-to-date input here.

    Nothing below the primary threshold. Main rate between the primary
    threshold and the upper earnings limit. Upper rate above that.
    Thresholds differ for weekly and monthly pay.

    Raise UnsupportedPayslip for any category other than "A".
    """
    if category != "A":
        raise UnsupportedPayslip(
            f"NI category {category} is outside the MVP scope"
        )

    gross = to_money(gross_this_period)

    thresholds = RATES["ni"][frequency]
    primary_threshold = thresholds["primary_threshold"]
    upper_earnings_limit = thresholds["upper_earnings_limit"]

    if gross <= primary_threshold:
        return Decimal("0")

    main_band = min(gross, upper_earnings_limit) - primary_threshold
    upper_band = max(
        gross - upper_earnings_limit,
        Decimal("0"),
    )

    due = (
        main_band * RATES["ni"]["main_rate"]
        + upper_band * RATES["ni"]["upper_rate"]
    )

    return due.quantize(Decimal("0.01"))


# --------------------------------------------------------------------------
# 4. Student loan
# --------------------------------------------------------------------------

def student_loan_due(
    gross_this_period: Decimal,
    plan: StudentLoanPlan,
    frequency: Frequency,
) -> Decimal:
    """
    Student loan deduction for THIS PERIOD.

    Also never cumulative. Take the annual threshold for the plan, divide
    by the number of periods in the year, and apply the plan's rate to
    anything above it.

    Round DOWN to a whole pound. Student loan deductions are always whole
    pounds, unlike tax and NI.
    """
    gross = to_money(gross_this_period)

    if plan not in RATES["student_loans"]:
        raise UnsupportedPayslip(
            f"Student loan plan {plan} is outside the MVP scope"
        )

    loan = RATES["student_loans"][plan]
    periods = periods_in_year(frequency)

    threshold_this_period = loan["threshold"] / Decimal(periods)
    amount_over_threshold = gross - threshold_this_period

    if amount_over_threshold <= 0:
        return Decimal("0")

    due = amount_over_threshold * loan["rate"]

    return due.quantize(Decimal("1"), rounding=ROUND_DOWN)

# --------------------------------------------------------------------------
# 5. Annualising
# --------------------------------------------------------------------------

def annualise(
    gross_this_period: Decimal,
    gross_ytd: Decimal,
    period_number: int,
    frequency: Frequency,
) -> Decimal:
    """
    Estimate total pay for the whole tax year if things carry on as they are.

    Year to date, plus this period's gross repeated for the periods left:
        gross_ytd + gross_this_period * (periods_in_year - period_number)

    This one matters for the findings layer. It is how we spot someone
    whose whole year's pay sits under the personal allowance but who is
    paying income tax anyway.
    """
    periods = periods_in_year(frequency)

    return gross_ytd + gross_this_period * (periods - period_number)


# --------------------------------------------------------------------------
# 6. What-if projection (do this one last)
# --------------------------------------------------------------------------

def project_with_extra_hours(
    hourly_rate: Decimal,
    current_hours: Decimal,
    extra_hours: Decimal,
    facts: PayPeriodFacts,
) -> PayBreakdown:
    """
    What one pay period would look like with extra hours worked.

    Work out the new gross, then reuse the functions above to get tax, NI
    and student loan on that figure. Return a PayBreakdown.

    Do this last. It is only a wrapper around everything else.
    """
    raise NotImplementedError
