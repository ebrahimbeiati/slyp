# """
# Calculation layer — OWNER: Ayaan

# Works out what someone SHOULD be paying, given the numbers off a payslip.
# Pure functions: same inputs always give the same output. No files, no
# network, no AI, no payslips.

# IMPORTANT: take every rate and threshold below from gov.uk for 2026/27.
# The values currently in RATES are placeholders and are very likely wrong.
# Replace them and delete this warning.

#   Income tax:    https://www.gov.uk/income-tax-rates
#   NI thresholds: https://www.gov.uk/guidance/rates-and-thresholds-for-employers
#   Student loans: https://www.gov.uk/repaying-your-student-loan/what-you-pay
#   Tax codes:     https://www.gov.uk/tax-codes

# Scope for the MVP: England/Northern Ireland rates, weekly and monthly pay,
# codes 1257L / BR / D0 / 0T / K (with optional S or C prefix), NI category A,
# student loan plans 1, 2, 4, 5 and PG. Anything else raises UnsupportedPayslip.
# """

# from __future__ import annotations

# import re
# from decimal import Decimal

# from .types import (
#     Frequency,
#     PayBreakdown,
#     PayPeriodFacts,
#     StudentLoanPlan,
#     TaxCode,
#     UnsupportedPayslip,
#     periods_in_year,
#     to_money,
# )


# # --------------------------------------------------------------------------
# # Rates and thresholds — ALL PLACEHOLDERS, REPLACE FROM GOV.UK
# # --------------------------------------------------------------------------

# RATES = {
#     "personal_allowance": Decimal("12570"),
#     "basic_rate": Decimal("0.20"),
#     "basic_rate_limit": Decimal("37700"),      # taxable pay above allowance
#     "higher_rate": Decimal("0.40"),
#     "higher_rate_limit": Decimal("125140"),    # total income
#     "additional_rate": Decimal("0.45"),
#     "allowance_taper_threshold": Decimal("100000"),

#     "ni": {
#         "monthly": {
#             "primary_threshold": Decimal("1048"),
#             "upper_earnings_limit": Decimal("4189"),
#         },
#         "weekly": {
#             "primary_threshold": Decimal("242"),
#             "upper_earnings_limit": Decimal("967"),
#         },
#         "main_rate": Decimal("0.08"),
#         "upper_rate": Decimal("0.02"),
#     },

#     "student_loans": {
#         # annual thresholds; divide by periods in year
#         "1": {"threshold": Decimal("26065"), "rate": Decimal("0.09")},
#         "2": {"threshold": Decimal("28470"), "rate": Decimal("0.09")},
#         "4": {"threshold": Decimal("32745"), "rate": Decimal("0.09")},
#         "5": {"threshold": Decimal("25000"), "rate": Decimal("0.09")},
#         "PG": {"threshold": Decimal("21000"), "rate": Decimal("0.06")},
#     },
# }


# # --------------------------------------------------------------------------
# # 1. Tax code parsing
# # --------------------------------------------------------------------------

# def parse_tax_code(code: str) -> TaxCode:
#     """
#     Parse a tax code as printed on a payslip into a TaxCode object.

#     Handles: "1257L", "1257L W1", "1257L M1", "1257LX", "BR", "D0", "D1",
#     "0T", "K475", and an optional leading "S" (Scotland) or "C" (Wales).
#     Case and spacing vary between payroll systems, so normalise first.

#     The number in a standard code is the annual allowance divided by 10:
#         1257L -> free_pay_annual = 12570

#     A K code is the reverse. K475 means £4,750 is ADDED to taxable pay,
#     so return free_pay_annual = -4750.

#     W1, M1 and X all mean the same thing: non-cumulative. Set
#     cumulative=False. Everything else is cumulative.

#     Raise UnsupportedPayslip for "NT" and for anything unparseable.
#     """
#     raw = code.strip().upper()
#     compact = "".join(raw.split())

#     # Normal tax codes are cumulative unless they use W1, M1 or X
#     cumulative = True

#     for suffix in ("W1", "M1", "X"):
#         if compact.endswith(suffix):
#             cumulative = False
#             compact = compact[:-len(suffix)]
#             break

#     # Default region is England / Northern Ireland
#     region = "UK"

#     # Record Scottish or Welsh prefix
#     if compact.startswith(("S", "C")):
#         region = compact[0]
#         compact = compact[1:]

#     # NT is outside the MVP
#     if compact == "NT":
#         raise UnsupportedPayslip("NT tax codes are outside the MVP scope")

#     # BR, D0, D1 and 0T give no personal allowance
#     if compact in {"BR", "D0", "D1", "0T"}:
#         return TaxCode(
#             raw=raw,
#             kind=compact,
#             free_pay_annual=Decimal("0"),
#             cumulative=cumulative,
#             region=region,
#         )

#     # K code: e.g. K475 means a negative £4,750 allowance
#     k_match = re.fullmatch(r"K(\d+)", compact)

#     if k_match:
#         return TaxCode(
#             raw=raw,
#             kind="K",
#             free_pay_annual=-(Decimal(k_match.group(1)) * Decimal("10")),
#             cumulative=cumulative,
#             region=region,
#         )

#     # Standard code: e.g. 1257L means £12,570 allowance
#     standard_match = re.fullmatch(r"(\d+)L", compact)

#     if standard_match:
#         return TaxCode(
#             raw=raw,
#             kind="standard",
#             free_pay_annual=Decimal(standard_match.group(1)) * Decimal("10"),
#             cumulative=cumulative,
#             region=region,
#         )

#     # Anything we don't understand is outside the MVP
#     raise UnsupportedPayslip(
#         f"Unsupported or unparseable tax code: {raw}"
#     )


# # --------------------------------------------------------------------------
# # 2. Income tax
# # --------------------------------------------------------------------------

# def income_tax_due(facts: PayPeriodFacts) -> Decimal:
#     """
#     Income tax that should be deducted THIS PERIOD.

#     Two different calculations depending on the code's basis.

#     CUMULATIVE (the normal case):
#       1. Allowance available so far this year
#              = free_pay_annual * period_number / periods_in_year
#       2. Taxable pay so far  = gross_ytd - allowance so far
#       3. Apply the bands to that figure -> total tax due for the year to date
#       4. This period's tax = tax due to date - tax already paid in earlier
#          periods. Earlier tax is not passed in, so derive it by running the
#          same calculation for period_number - 1 with the year-to-date gross
#          at that point (gross_ytd - gross_this_period).

#     NON-CUMULATIVE (W1/M1/X):
#       Ignore the year to date entirely. Give one period's worth of
#       allowance and one period's worth of each band, and tax this
#       period's gross on its own.

#     Never return a negative figure: if the calculation comes out below
#     zero (a refund is due) return Decimal("0"). The findings layer deals
#     with refunds, not the calculator.

#     Raise UnsupportedPayslip if annualised income is above the allowance
#     taper threshold, or if the code region is not "UK".
#     """
#     raise NotImplementedError


# # --------------------------------------------------------------------------
# # 3. National Insurance
# # --------------------------------------------------------------------------

# def national_insurance_due(
#     gross_this_period: Decimal,
#     frequency: Frequency,
#     category: str = "A",
# ) -> Decimal:
#     """
#     Employee National Insurance for THIS PERIOD.

#     NI is never cumulative. Every pay period is worked out on its own,
#     which is why there is no year-to-date input here.

#     Nothing below the primary threshold. Main rate between the primary
#     threshold and the upper earnings limit. Upper rate above that.
#     Thresholds differ for weekly and monthly pay.

#     Raise UnsupportedPayslip for any category other than "A".
#     """
#     if category != "A":
#         raise UnsupportedPayslip(
#             f"NI category {category} is outside the MVP scope"
#         )

#     gross = to_money(gross_this_period)

#     thresholds = RATES["ni"][frequency]
#     primary_threshold = thresholds["primary_threshold"]
#     upper_earnings_limit = thresholds["upper_earnings_limit"]

#     if gross <= primary_threshold:
#         return Decimal("0")

#     main_band = min(gross, upper_earnings_limit) - primary_threshold
#     upper_band = max(
#         gross - upper_earnings_limit,
#         Decimal("0"),
#     )

#     due = (
#         main_band * RATES["ni"]["main_rate"]
#         + upper_band * RATES["ni"]["upper_rate"]
#     )

#     return due.quantize(Decimal("0.01"))


# # --------------------------------------------------------------------------
# # 4. Student loan
# # --------------------------------------------------------------------------

# def student_loan_due(
#     gross_this_period: Decimal,
#     plan: StudentLoanPlan,
#     frequency: Frequency,
# ) -> Decimal:
#     """
#     Student loan deduction for THIS PERIOD.

#     Also never cumulative. Take the annual threshold for the plan, divide
#     by the number of periods in the year, and apply the plan's rate to
#     anything above it.

#     Round DOWN to a whole pound. Student loan deductions are always whole
#     pounds, unlike tax and NI.
#     """
#     raise NotImplementedError


# # --------------------------------------------------------------------------
# # 5. Annualising
# # --------------------------------------------------------------------------

# def annualise(
#     gross_this_period: Decimal,
#     gross_ytd: Decimal,
#     period_number: int,
#     frequency: Frequency,
# ) -> Decimal:
#     """
#     Estimate total pay for the whole tax year if things carry on as they are.

#     Year to date, plus this period's gross repeated for the periods left:
#         gross_ytd + gross_this_period * (periods_in_year - period_number)

#     This one matters for the findings layer. It is how we spot someone
#     whose whole year's pay sits under the personal allowance but who is
#     paying income tax anyway.
#     """
#     raise NotImplementedError


# # --------------------------------------------------------------------------
# # 6. What-if projection (do this one last)
# # --------------------------------------------------------------------------

# def project_with_extra_hours(
#     hourly_rate: Decimal,
#     current_hours: Decimal,
#     extra_hours: Decimal,
#     facts: PayPeriodFacts,
# ) -> PayBreakdown:
#     """
#     What one pay period would look like with extra hours worked.

#     Work out the new gross, then reuse the functions above to get tax, NI
#     and student loan on that figure. Return a PayBreakdown.

#     Do this last. It is only a wrapper around everything else.
#     """
#     raise NotImplementedError

"""
Slyp calculation engine — v1
=============================

Deterministic UK PAYE calculation engine.

Responsibilities
----------------
This module calculates what SHOULD be deducted from a payslip.

It does NOT:
    - read PDFs
    - extract text
    - interpret employer names
    - generate user-facing findings
    - invent missing payslip values

Those responsibilities belong to the extraction and findings layers.

Supported MVP
-------------
    - England
    - Wales
    - Northern Ireland
    - Monthly pay
    - Weekly pay
    - Standard tax codes
    - BR
    - D0
    - D1
    - 0T
    - K codes
    - NT is rejected
    - NI categories supported by the MVP
    - Student Loan Plans 1, 2, 4, 5
    - Postgraduate Loan

Not supported by this MVP
-------------------------
    - Scottish income tax
    - salary sacrifice
    - benefits in kind
    - statutory payments
    - directors' annual NI method
    - income above £100,000 / Personal Allowance taper
    - complex pension tax relief
    - multiple simultaneous student-loan plans

Important
---------
The engine uses Decimal everywhere.

Never use float for money.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Optional

from .types import (
    Frequency,
    PayBreakdown,
    PayPeriodFacts,
    StudentLoanPlan,
    TaxCode,
    TaxCodeKind,
    UnsupportedPayslip,
    to_money,
)

# ============================================================================
# CONSTANTS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

TWO_DP = Decimal("0.01")
WHOLE_POUND = Decimal("1")


# ============================================================================
# 2026/27 UK TAX CONSTANTS
# ============================================================================

TAX_YEAR = "2026/27"

# Tax years the rates/thresholds in this module are correct for. A
# payslip whose derived tax year isn't in this set must be refused, not
# calculated with the wrong year's rates - keep this beside the rates
# constants below so it's updated in the same change when a new tax
# year is added.
SUPPORTED_TAX_YEARS: frozenset[str] = frozenset({TAX_YEAR})

# ONE YEAR ONLY, deliberately. There is no per-year rate selection in
# this module - every constant below is a single 2026/27 value - so a
# second entry in SUPPORTED_TAX_YEARS would silently run an older payslip
# through this year's numbers. Supporting another year means making the
# constants below year-aware FIRST, in the same change.
#
# What running a 2025/26 payslip through these constants would cost,
# checked against the constants rather than assumed:
#   - Income tax: NOTHING. Personal Allowance (12,570), basic rate limit
#     (37,700), higher (50,270) and additional (125,140) thresholds have
#     been frozen since 2021/22 and stay frozen to 2027/28, so 2025/26
#     and 2026/27 are identical.
#   - National Insurance: NOTHING. The 8%/2% employee rates and the
#     PT/UEL are the same in both years.
#   - Student loans: WRONG for plans 1, 2 and 4. Those thresholds are
#     uprated every April and the values below are the 2026/27 ones
#     (~£835-1,050/yr higher than 2025/26), so a 2025/26 payslip with a
#     plan 1/2/4 loan gets too little expected repayment - roughly £7/mo
#     on plan 2 - and can raise a student-loan mismatch that isn't real.
#     Plan 5 (25,000) and PG (21,000) are frozen, so those two are the
#     only ones that would survive the swap unharmed.
#
# That last point is the whole reason this is a refusal and not a
# warning: two of the five plans would produce a confident, wrong figure.

# Standard Personal Allowance.
PERSONAL_ALLOWANCE = Decimal("12570")

# Basic-rate band after allowances.
BASIC_RATE_LIMIT = Decimal("37700")

# Personal allowance + basic-rate limit.
HIGHER_RATE_THRESHOLD = Decimal("50270")

# Additional-rate threshold.
ADDITIONAL_RATE_THRESHOLD = Decimal("125140")

# Personal Allowance taper begins here.
PERSONAL_ALLOWANCE_TAPER_START = Decimal("100000")


# Income-tax rates.
BASIC_RATE = Decimal("0.20")
HIGHER_RATE = Decimal("0.40")
ADDITIONAL_RATE = Decimal("0.45")


# ============================================================================
# NATIONAL INSURANCE 2026/27
# ============================================================================

# Employee Class 1 NI thresholds for category A.
#
# Annual:
#   Primary Threshold = £12,570
#   Upper Earnings Limit = £50,270
#
# Monthly:
#   £1,048
#   £4,189
#
# Weekly:
#   £242
#   £967
#
# HMRC's 2026/27 employee rates:
#   8% between PT and UEL
#   2% above UEL
#
# Source:
# GOV.UK National Insurance rates 2026/27.
NI_ANNUAL_PRIMARY_THRESHOLD = Decimal("12570")
NI_ANNUAL_UPPER_EARNINGS_LIMIT = Decimal("50270")

NI_MONTHLY_PRIMARY_THRESHOLD = Decimal("1048")
NI_MONTHLY_UPPER_EARNINGS_LIMIT = Decimal("4189")

NI_WEEKLY_PRIMARY_THRESHOLD = Decimal("242")
NI_WEEKLY_UPPER_EARNINGS_LIMIT = Decimal("967")

NI_MAIN_RATE = Decimal("0.08")
NI_UPPER_RATE = Decimal("0.02")


# ============================================================================
# STUDENT LOANS 2026/27
# ============================================================================

STUDENT_LOAN_THRESHOLDS_MONTHLY: dict[str, Decimal] = {
    "1": Decimal("2241.66"),
    "2": Decimal("2448.75"),
    "4": Decimal("2816.25"),
    "5": Decimal("2083.33"),
    "PG": Decimal("1750.00"),
}

STUDENT_LOAN_THRESHOLDS_WEEKLY: dict[str, Decimal] = {
    "1": Decimal("517.30"),
    "2": Decimal("565.09"),
    "4": Decimal("649.90"),
    "5": Decimal("480.76"),
    "PG": Decimal("403.84"),
}

STUDENT_LOAN_RATES: dict[str, Decimal] = {
    "1": Decimal("0.09"),
    "2": Decimal("0.09"),
    "4": Decimal("0.09"),
    "5": Decimal("0.09"),
    "PG": Decimal("0.06"),
}


# ============================================================================
# NI CATEGORY CONFIGURATION
# ============================================================================

"""
Employee NI rates vary by category.

The MVP mainly expects category A.

We include the common categories so that a payslip containing a different
category does not silently receive category A treatment.

Rates below are employee rates for 2026/27.
"""

NI_CATEGORY_RATES: dict[str, tuple[Decimal, Decimal]] = {
    # category: (main_rate, upper_rate)
    "A": (
        Decimal("0.08"),
        Decimal("0.02"),
    ),
    # Married women's / widow's reduced rate.
    "B": (
        Decimal("0.0185"),
        Decimal("0.02"),
    ),
    # No employee NI.
    "C": (
        ZERO,
        ZERO,
    ),
    # Deferred NI.
    "D": (
        Decimal("0.02"),
        Decimal("0.02"),
    ),
    "E": (
        Decimal("0.0185"),
        Decimal("0.02"),
    ),
    "F": (
        Decimal("0.08"),
        Decimal("0.02"),
    ),
    "H": (
        Decimal("0.08"),
        Decimal("0.02"),
    ),
    "I": (
        Decimal("0.0185"),
        Decimal("0.02"),
    ),
    "J": (
        Decimal("0.02"),
        Decimal("0.02"),
    ),
    "L": (
        Decimal("0.02"),
        Decimal("0.02"),
    ),
    "M": (
        Decimal("0.08"),
        Decimal("0.02"),
    ),
    "N": (
        Decimal("0.08"),
        Decimal("0.02"),
    ),
    "V": (
        Decimal("0.08"),
        Decimal("0.02"),
    ),
    "Z": (
        Decimal("0.02"),
        Decimal("0.02"),
    ),
}


# ============================================================================
# MONEY HELPERS
# ============================================================================


def money(value: Decimal | int | str) -> Decimal:
    """
    Round a value to two decimal places.

    ROUND_HALF_UP is used for normal monetary presentation.
    """
    return to_money(value).quantize(
        TWO_DP,
        rounding=ROUND_HALF_UP,
    )


def floor_pound(value: Decimal) -> Decimal:
    """
    Round down to a whole pound.

    Used for student loan deductions because HMRC's deduction method
    truncates the calculated amount to whole pounds.
    """
    return to_money(value).quantize(
        WHOLE_POUND,
        rounding=ROUND_DOWN,
    )


def non_negative(value: Decimal) -> Decimal:
    return max(ZERO, to_money(value))


# ============================================================================
# FREQUENCY HELPERS
# ============================================================================


def periods_in_year(frequency: Frequency) -> int:
    """
    Number of PAYE periods in the tax year.
    """
    if frequency == "monthly":
        return 12

    if frequency == "weekly":
        return 52

    raise UnsupportedPayslip(f"Unsupported pay frequency: {frequency}")


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

    This is a gate, not a displayed figure: it exists so the findings layer
    can detect someone whose full-year earnings look set to land under the
    Personal Allowance while tax is still being deducted. Its output must
    never be shown to the user as a projected pound amount.
    """
    periods = periods_in_year(frequency)

    return to_money(gross_ytd) + to_money(gross_this_period) * Decimal(
        periods - period_number
    )


# ============================================================================
# TAX YEAR VALIDATION
# ============================================================================


def validate_tax_year(tax_year: Optional[str]) -> None:
    """
    Raise UnsupportedPayslip unless `tax_year` is one this engine has
    rates for.

    `None` (tax year could not be derived - the pay date was unreadable
    or absent) refuses too, rather than silently assuming the current
    tax year: a payslip with no determinable date is exactly the case
    where guessing "current year" would be most likely wrong and least
    likely to be noticed.

    Enforced unconditionally. There is deliberately no bypass flag: one
    existed for the demo, and a constant that turns a correctness guard
    off is exactly the kind of thing that survives into production. See
    SUPPORTED_TAX_YEARS for what an unsupported year would actually get
    wrong (student loan plans 1, 2 and 4).
    """
    if tax_year is None:
        raise UnsupportedPayslip(
            "The tax year for this payslip could not be determined."
        )

    if tax_year not in SUPPORTED_TAX_YEARS:
        raise UnsupportedPayslip(
            f"This payslip is from tax year {tax_year}, which is not "
            f"currently supported."
        )


# ============================================================================
# TAX CODE PARSING
# ============================================================================


def parse_tax_code(
    raw_code: str,
) -> TaxCode:
    """
    Parse a UK tax code.

    Examples
    --------
    1257L       -> £12,570 annual allowance
    1060L       -> £10,600 annual allowance
    BR          -> £0 allowance, all basic-rate
    D0          -> £0 allowance, all higher-rate
    D1          -> £0 allowance, all additional-rate
    0T          -> £0 allowance, normal bands
    K475        -> -£4,750 allowance
    1257L M1    -> £12,570 allowance, non-cumulative
    1257L W1    -> £12,570 allowance, non-cumulative
    1257L X     -> £12,570 allowance, non-cumulative
    """

    if not raw_code:
        raise UnsupportedPayslip("Tax code is missing.")

    raw = raw_code.strip().upper()

    if not raw:
        raise UnsupportedPayslip("Tax code is empty.")

    # Remove normal spacing.
    compact = raw.replace(" ", "")

    # Detect emergency/non-cumulative suffixes.
    cumulative = True

    for suffix in ("M1", "W1", "X"):
        if compact.endswith(suffix):
            cumulative = False
            compact = compact[: -len(suffix)]
            break

    # Scottish (S) or Welsh (C) prefix. Applying rest-of-UK bands to these
    # would produce a confidently wrong number, so refuse rather than
    # approximate. Standard codes always start with a digit, so this
    # cannot collide with them.
    if compact[:1] == "S":
        raise UnsupportedPayslip(f"Scottish tax codes are outside the MVP: {raw}")

    if compact[:1] == "C":
        raise UnsupportedPayslip(f"Welsh tax codes are outside the MVP: {raw}")

    # NT — no tax due, always. Distinct from 0T: NT is exempt, not banded
    # on a zero allowance.
    if compact == "NT":
        return TaxCode(
            raw=raw,
            kind="NT",
            free_pay_annual=ZERO,
            cumulative=cumulative,
            region="UK",
        )

    # BR
    if compact == "BR":
        return TaxCode(
            raw=raw,
            kind="BR",
            free_pay_annual=ZERO,
            cumulative=cumulative,
            region="UK",
        )

    # D0
    if compact == "D0":
        return TaxCode(
            raw=raw,
            kind="D0",
            free_pay_annual=ZERO,
            cumulative=cumulative,
            region="UK",
        )

    # D1
    if compact == "D1":
        return TaxCode(
            raw=raw,
            kind="D1",
            free_pay_annual=ZERO,
            cumulative=cumulative,
            region="UK",
        )

    # 0T
    if compact == "0T":
        return TaxCode(
            raw=raw,
            kind="0T",
            free_pay_annual=ZERO,
            cumulative=cumulative,
            region="UK",
        )

    # K code. Adds notional pay rather than deducting free pay, and carries
    # a regulatory limit on how much can be added — out of MVP scope.
    if compact.startswith("K"):
        raise UnsupportedPayslip(f"K tax codes are outside the MVP: {raw}")

    # Standard numeric + letter tax code.
    #
    # Examples:
    #   1257L
    #   1060L
    #   500T
    #   0L
    #
    # The numeric portion represents tens of pounds.
    if compact[-1].isalpha():
        number = compact[:-1]

        if number.isdigit():
            free_pay = Decimal(number) * Decimal("10")

            return TaxCode(
                raw=raw,
                kind="standard",
                free_pay_annual=free_pay,
                cumulative=cumulative,
                region="UK",
            )

    raise UnsupportedPayslip(f"Unrecognised tax code: {raw}")


# ============================================================================
# PERSONAL ALLOWANCE
# ============================================================================


def personal_allowance_for_income(
    annual_income: Decimal,
) -> Decimal:
    """
    Calculate Personal Allowance.

    £12,570 normally.

    Above £100,000, allowance is reduced by £1 for every £2 of
    adjusted net income above £100,000.

    At £125,140 the allowance reaches zero.

    The MVP deliberately rejects income above £100,000 elsewhere in the
    engine because the payslip contract says the allowance taper is outside
    MVP scope. This helper is kept explicit so the rule is not hidden.
    """

    annual_income = non_negative(annual_income)

    if annual_income <= PERSONAL_ALLOWANCE_TAPER_START:
        return PERSONAL_ALLOWANCE

    excess = annual_income - PERSONAL_ALLOWANCE_TAPER_START

    reduction = excess / Decimal("2")

    allowance = PERSONAL_ALLOWANCE - reduction

    return max(
        ZERO,
        allowance,
    )


# ============================================================================
# TAXABLE INCOME
# ============================================================================


def taxable_income(
    annual_gross: Decimal,
    tax_code: TaxCode,
) -> Decimal:
    """
    Calculate taxable annual income after the allowance represented by
    the tax code.

    For normal tax codes:
        taxable = gross - allowance

    For K codes:
        negative allowance increases taxable income.
    """

    annual_gross = non_negative(annual_gross)

    allowance = tax_code.free_pay_annual

    taxable = annual_gross - allowance

    return max(
        ZERO,
        taxable,
    )


# ============================================================================
# ANNUAL INCOME TAX
# ============================================================================


def annual_income_tax(
    annual_gross: Decimal,
    tax_code: TaxCode,
) -> Decimal:
    """
    Calculate annual UK income tax for England/Wales/Northern Ireland.

    Supported:
        standard
        BR
        D0
        D1
        0T
        K

    The tax code determines the available allowance.

    Standard tax bands:
        20% basic
        40% higher
        45% additional
    """

    annual_gross = non_negative(annual_gross)

    if annual_gross > PERSONAL_ALLOWANCE_TAPER_START:
        raise UnsupportedPayslip(
            "Income above £100,000 is outside the MVP because "
            "Personal Allowance tapering is not supported."
        )

    if tax_code.kind == "NT":
        return ZERO

    # ------------------------------------------------------------
    # BR
    # ------------------------------------------------------------

    if tax_code.kind == "BR":
        return money(annual_gross * BASIC_RATE)

    # ------------------------------------------------------------
    # D0
    # ------------------------------------------------------------

    if tax_code.kind == "D0":
        return money(annual_gross * HIGHER_RATE)

    # ------------------------------------------------------------
    # D1
    # ------------------------------------------------------------

    if tax_code.kind == "D1":
        return money(annual_gross * ADDITIONAL_RATE)

    # ------------------------------------------------------------
    # 0T and standard/K codes
    # ------------------------------------------------------------

    taxable = taxable_income(
        annual_gross,
        tax_code,
    )

    if taxable <= ZERO:
        return ZERO

    # Basic rate.
    basic_amount = min(
        taxable,
        BASIC_RATE_LIMIT,
    )

    tax = basic_amount * BASIC_RATE

    # Higher rate.
    higher_amount = min(
        max(
            ZERO,
            taxable - BASIC_RATE_LIMIT,
        ),
        ADDITIONAL_RATE_THRESHOLD - BASIC_RATE_LIMIT,
    )

    tax += higher_amount * HIGHER_RATE

    # Additional rate.
    additional_amount = max(
        ZERO,
        taxable - ADDITIONAL_RATE_THRESHOLD,
    )

    tax += additional_amount * ADDITIONAL_RATE

    return money(tax)


# ============================================================================
# CUMULATIVE PAYE
# ============================================================================


def cumulative_income_tax_due(
    facts: PayPeriodFacts,
) -> Decimal:
    """
        Calculate the income tax that should be deducted THIS pay period.

        This is the important distinction between:

            annual_income_tax()

    and:

            cumulative_income_tax_due()

    A cumulative PAYE payslip does not simply calculate:

        annual tax / 12

    for every month.

    Instead, it calculates the tax due on cumulative taxable pay up to
    the current period and subtracts the tax already due in previous periods.

    Example:

        Month 5 gross YTD = £15,000

    The engine calculates the tax due on the £15,000 cumulative figure,
    then subtracts the amount that should already have been collected in
    months 1-4.

    For a non-cumulative W1/M1/X code, only the current pay period is used.
    """

    validate_pay_period_facts(facts)

    if facts.tax_code.cumulative is False:
        return non_cumulative_income_tax_due(facts)

    current_period = facts.period_number

    cumulative_tax = cumulative_tax_due_to_date(
        facts.gross_ytd,
        current_period,
        facts.frequency,
        facts.tax_code,
    )

    # PAYE cumulative calculation.
    #
    # Previous tax can be reconstructed using:
    #
    # gross YTD minus current gross
    #
    # and period number - 1.
    previous_gross_ytd = facts.gross_ytd - facts.gross_this_period

    if current_period <= 1 or previous_gross_ytd <= ZERO:
        return money(cumulative_tax)

    previous_tax = cumulative_tax_due_to_date(
        previous_gross_ytd,
        current_period - 1,
        facts.frequency,
        facts.tax_code,
    )

    current_tax = cumulative_tax - previous_tax

    return money(
        max(
            ZERO,
            current_tax,
        )
    )


def cumulative_tax_due_to_date(
    gross_ytd: Decimal,
    period_number: int,
    frequency: Frequency,
    tax_code: TaxCode,
) -> Decimal:
    """
    Tax that should have been deducted in total, from period 1 through the
    given period, under a cumulative tax code.

    Used both by cumulative_income_tax_due() (this period's figure is
    to-date minus the prior period's to-date figure) and by the findings
    layer, which uses it to work out what a cumulative code WOULD have
    deducted by now — the comparison an emergency/non-cumulative code's
    overpayment estimate depends on.
    """

    periods = periods_in_year(frequency)

    accumulated_allowance = (
        tax_code.free_pay_annual * Decimal(period_number) / Decimal(periods)
    )

    # K codes have negative allowance.
    cumulative_taxable = max(
        ZERO,
        non_negative(gross_ytd) - accumulated_allowance,
    )

    return cumulative_tax_on_taxable_amount(
        cumulative_taxable,
        tax_code,
    )


def cumulative_tax_on_taxable_amount(
    taxable: Decimal,
    tax_code: TaxCode,
) -> Decimal:
    """
    Apply UK tax bands to a cumulative taxable amount.

    This function receives TAXABLE income, not gross income.
    """

    taxable = non_negative(taxable)

    if taxable == ZERO:
        return ZERO

    if tax_code.kind == "BR":
        return money(taxable * BASIC_RATE)

    if tax_code.kind == "D0":
        return money(taxable * HIGHER_RATE)

    if tax_code.kind == "D1":
        return money(taxable * ADDITIONAL_RATE)

    # 0T and standard/K codes use normal bands.
    basic = min(
        taxable,
        BASIC_RATE_LIMIT,
    )

    tax = basic * BASIC_RATE

    higher = min(
        max(
            ZERO,
            taxable - BASIC_RATE_LIMIT,
        ),
        ADDITIONAL_RATE_THRESHOLD - BASIC_RATE_LIMIT,
    )

    tax += higher * HIGHER_RATE

    additional = max(
        ZERO,
        taxable - ADDITIONAL_RATE_THRESHOLD,
    )

    tax += additional * ADDITIONAL_RATE

    return money(tax)


# ============================================================================
# NON-CUMULATIVE PAYE
# ============================================================================


def non_cumulative_income_tax_due(
    facts: PayPeriodFacts,
) -> Decimal:
    """
    Calculate W1/M1/X PAYE.

    Each pay period is treated independently.

    Example:

        1257L M1

    receives one month's Personal Allowance rather than the cumulative
    allowance for the whole tax year.
    """

    periods = periods_in_year(facts.frequency)

    period_allowance = facts.tax_code.free_pay_annual / Decimal(periods)

    taxable = facts.gross_this_period - period_allowance

    taxable = max(
        ZERO,
        taxable,
    )

    return cumulative_tax_on_taxable_amount(
        taxable,
        facts.tax_code,
    )


# ============================================================================
# INCOME TAX — PUBLIC ENTRY POINT
# ============================================================================


def income_tax_due(
    facts: PayPeriodFacts,
) -> Decimal:
    """
    Income tax that should be deducted THIS pay period.

    Single entry point for the findings layer and the API. Owns dispatch
    between the cumulative and non-cumulative calculations; BR, D0 and D1
    are handled inside both via cumulative_tax_on_taxable_amount(). NT is
    always zero regardless of basis.

    Raises UnsupportedPayslip — never approximates — for anything outside
    MVP scope: Scottish/Welsh tax codes, K codes, an unparseable tax code,
    an unsupported NI category, or an out-of-range period number. Callers
    must treat that as "we cannot tell", not as zero or a hedged figure.
    """

    validate_pay_period_facts(facts)

    if facts.tax_code.kind == "NT":
        return ZERO

    return cumulative_income_tax_due(facts)


# ============================================================================
# NATIONAL INSURANCE
# ============================================================================


def national_insurance_due(
    gross: Decimal,
    frequency: Frequency,
    ni_category: str = "A",
) -> Decimal:
    """
    Calculate employee Class 1 National Insurance.

    2026/27 standard category A:

        Monthly:
            £0 - £1,048       0%
            £1,048 - £4,189   8%
            > £4,189          2%

        Weekly:
            £0 - £242         0%
            £242 - £967       8%
            > £967            2%

    The calculation is per pay period.
    """

    gross = non_negative(gross)

    category = (ni_category or "A").strip().upper()

    if category not in NI_CATEGORY_RATES:
        raise UnsupportedPayslip(f"Unsupported National Insurance category: {category}")

    main_rate, upper_rate = NI_CATEGORY_RATES[category]

    if frequency == "monthly":
        primary_threshold = NI_MONTHLY_PRIMARY_THRESHOLD

        upper_limit = NI_MONTHLY_UPPER_EARNINGS_LIMIT

    elif frequency == "weekly":
        primary_threshold = NI_WEEKLY_PRIMARY_THRESHOLD

        upper_limit = NI_WEEKLY_UPPER_EARNINGS_LIMIT

    else:
        raise UnsupportedPayslip(f"Unsupported NI frequency: {frequency}")

    if gross <= primary_threshold:
        return ZERO

    main_band = (
        min(
            gross,
            upper_limit,
        )
        - primary_threshold
    )

    main_band = max(
        ZERO,
        main_band,
    )

    upper_band = max(
        ZERO,
        gross - upper_limit,
    )

    contribution = main_band * main_rate + upper_band * upper_rate

    return money(contribution)


# ============================================================================
# STUDENT LOAN
# ============================================================================


def student_loan_due(
    gross: Decimal,
    frequency: Frequency,
    plan: Optional[StudentLoanPlan],
) -> Decimal:
    """
    Calculate the student loan deduction for one pay period.

    2026/27:

        Plan 1: 9%
        Plan 2: 9%
        Plan 4: 9%
        Plan 5: 9%
        PG:     6%

    Student loan deductions are rounded DOWN to the nearest whole pound.
    """

    if plan is None:
        return ZERO

    if plan not in STUDENT_LOAN_RATES:
        raise UnsupportedPayslip(f"Unsupported student loan plan: {plan}")

    gross = non_negative(gross)

    if frequency == "monthly":
        threshold = STUDENT_LOAN_THRESHOLDS_MONTHLY[plan]

    elif frequency == "weekly":
        threshold = STUDENT_LOAN_THRESHOLDS_WEEKLY[plan]

    else:
        raise UnsupportedPayslip(f"Unsupported student loan frequency: {frequency}")

    if gross <= threshold:
        return ZERO

    excess = gross - threshold

    rate = STUDENT_LOAN_RATES[plan]

    deduction = excess * rate

    return floor_pound(deduction)


# ============================================================================
# FULL PAY BREAKDOWN
# ============================================================================


def calculate_pay_breakdown(
    facts: PayPeriodFacts,
) -> PayBreakdown:
    """
    Calculate the complete expected deduction breakdown.

    Returns:

        gross
        income tax
        National Insurance
        student loan
        pension employee

    Pension is deliberately NOT calculated here.

    The payslip supplies the pension amount because pension calculation
    depends on the employee's pension scheme, qualifying earnings,
    contribution basis, salary sacrifice and other scheme-specific rules.
    """

    validate_pay_period_facts(facts)

    income_tax = income_tax_due(facts)

    national_insurance = national_insurance_due(
        facts.gross_this_period,
        facts.frequency,
        facts.ni_category,
    )

    student_loan = student_loan_due(
        facts.gross_this_period,
        facts.frequency,
        facts.student_loan_plan,
    )

    return PayBreakdown(
        gross=money(facts.gross_this_period),
        income_tax=money(income_tax),
        national_insurance=money(national_insurance),
        student_loan=money(student_loan),
        pension_employee=ZERO,
    )


# ============================================================================
# NET PAY
# ============================================================================


def calculate_expected_net(
    facts: PayPeriodFacts,
    pension_employee: Decimal = ZERO,
) -> Decimal:
    """
    Calculate expected net pay.

    Pension is supplied separately because the engine cannot safely infer
    pension treatment from gross pay alone.
    """

    breakdown = calculate_pay_breakdown(facts)

    pension = money(pension_employee)

    net = (
        breakdown.gross
        - breakdown.income_tax
        - breakdown.national_insurance
        - breakdown.student_loan
        - pension
    )

    return money(
        max(
            ZERO,
            net,
        )
    )


# ============================================================================
# RECONCILIATION
# ============================================================================


def reconcile_payslip(
    gross: Decimal,
    income_tax: Decimal,
    national_insurance: Decimal,
    student_loan: Decimal = ZERO,
    pension_employee: Decimal = ZERO,
    other_deductions: Decimal = ZERO,
    net_pay: Decimal = ZERO,
) -> bool:
    """
    Check whether the payslip mathematically reconciles.

    gross
        -
    income tax
        -
    NI
        -
    student loan
        -
    pension
        -
    other deductions
        =
    net pay
    """

    expected_net = (
        money(gross)
        - money(income_tax)
        - money(national_insurance)
        - money(student_loan)
        - money(pension_employee)
        - money(other_deductions)
    )

    return money(expected_net) == money(net_pay)


# ============================================================================
# VALIDATION
# ============================================================================


def validate_pay_period_facts(
    facts: PayPeriodFacts,
) -> None:
    """
    Validate inputs before performing calculations.
    """

    if facts.gross_this_period < ZERO:
        raise ValueError("gross_this_period cannot be negative.")

    if facts.gross_ytd < ZERO:
        raise ValueError("gross_ytd cannot be negative.")

    if facts.gross_ytd < facts.gross_this_period:
        raise ValueError("gross_ytd must include this period's gross pay.")

    periods = periods_in_year(facts.frequency)

    if not (1 <= facts.period_number <= periods):
        raise ValueError(
            f"period_number must be between "
            f"1 and {periods} for "
            f"{facts.frequency} pay."
        )

    if facts.ni_category:
        category = facts.ni_category.upper()

        if category not in NI_CATEGORY_RATES:
            raise UnsupportedPayslip(f"Unsupported NI category: {category}")

    # Scotland is intentionally outside this MVP.
    if facts.tax_code.region == "S":
        raise UnsupportedPayslip("Scottish income tax is outside the MVP.")


# ============================================================================
# CONVENIENCE API
# ============================================================================


def calculate_from_values(
    *,
    gross_this_period: Decimal | str | int,
    gross_ytd: Decimal | str | int,
    tax_code: str,
    period_number: int,
    frequency: Frequency,
    ni_category: str = "A",
    student_loan_plan: Optional[StudentLoanPlan] = None,
    pension_employee: Decimal | str | int = ZERO,
) -> PayBreakdown:
    """
    Convenience function for the API layer.

    Example:

        result = calculate_from_values(
            gross_this_period="2500.00",
            gross_ytd="7500.00",
            tax_code="1257L",
            period_number=3,
            frequency="monthly",
            ni_category="A",
        )
    """

    parsed_tax_code = parse_tax_code(tax_code)

    facts = PayPeriodFacts(
        gross_this_period=to_money(gross_this_period),
        gross_ytd=to_money(gross_ytd),
        tax_code=parsed_tax_code,
        period_number=period_number,
        frequency=frequency,
        ni_category=ni_category.upper(),
        student_loan_plan=student_loan_plan,
    )

    breakdown = calculate_pay_breakdown(facts)

    return replace(
        breakdown,
        pension_employee=money(pension_employee),
    )


# ============================================================================
# DEBUG / DEVELOPMENT HELPERS
# ============================================================================


def explain_calculation(
    facts: PayPeriodFacts,
) -> dict[str, Decimal | str]:
    """
    Return a machine-readable calculation summary.

    Useful for development and tests.

    Do NOT expose this directly to users as financial advice.
    """

    breakdown = calculate_pay_breakdown(facts)

    return {
        "tax_year": TAX_YEAR,
        "frequency": facts.frequency,
        "period_number": facts.period_number,
        "tax_code": facts.tax_code.raw,
        "gross_this_period": breakdown.gross,
        "gross_ytd": facts.gross_ytd,
        "income_tax": breakdown.income_tax,
        "national_insurance": breakdown.national_insurance,
        "student_loan": breakdown.student_loan,
        "pension_employee": breakdown.pension_employee,
        "net_before_pension": (
            breakdown.gross
            - breakdown.income_tax
            - breakdown.national_insurance
            - breakdown.student_loan
        ),
    }


# ============================================================================
# DEVELOPMENT SELF-CHECKS
# ============================================================================


def _self_check_tax_codes() -> None:
    """
    Basic development assertions.

    These are not a substitute for pytest.
    """

    code = parse_tax_code("1257L")

    assert code.kind == "standard"

    assert code.free_pay_annual == Decimal("12570")

    assert code.cumulative is True

    code = parse_tax_code("1257L M1")

    assert code.cumulative is False

    code = parse_tax_code("BR")

    assert code.kind == "BR"
    assert code.free_pay_annual == ZERO

    code = parse_tax_code("K475")

    assert code.kind == "K"
    assert code.free_pay_annual == Decimal("-4750")


def _self_check_ni() -> None:
    """
    Check basic 2026/27 category A NI behaviour.
    """

    assert national_insurance_due(
        Decimal("1000"),
        "weekly",
        "A",
    ) == Decimal("60.64")

    assert national_insurance_due(
        Decimal("2000"),
        "monthly",
        "A",
    ) == Decimal("76.16")


def _self_check_student_loan() -> None:
    """
    Check official 2026/27 student loan examples.
    """

    # Plan 1:
    #
    # £2,750 - £2,241.66 = £508.34
    # 9% = £45.7506
    # round down = £45
    assert student_loan_due(
        Decimal("2750"),
        "monthly",
        "1",
    ) == Decimal("45")

    # Plan 4:
    #
    # £3,000 - £2,816.25 = £183.75
    # 9% = £16.5375
    # round down = £16
    assert student_loan_due(
        Decimal("3000"),
        "monthly",
        "4",
    ) == Decimal("16")


def _self_check_reconciliation() -> None:
    """
    Basic arithmetic reconciliation test.
    """

    assert reconcile_payslip(
        gross=Decimal("1000"),
        income_tax=Decimal("100"),
        national_insurance=Decimal("50"),
        net_pay=Decimal("850"),
    )

    assert not reconcile_payslip(
        gross=Decimal("1000"),
        income_tax=Decimal("100"),
        national_insurance=Decimal("50"),
        net_pay=Decimal("900"),
    )


def run_self_checks() -> None:
    """
    Run lightweight internal checks.

    Normally pytest should be used instead.
    """

    _self_check_tax_codes()
    _self_check_ni()
    _self_check_student_loan()
    _self_check_reconciliation()


if __name__ == "__main__":
    run_self_checks()
    print("Slyp calculation engine self-checks passed.")
