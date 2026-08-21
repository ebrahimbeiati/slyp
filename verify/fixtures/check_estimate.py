"""
Independent hand-calculation of both fixtures.

Deliberately imports NOTHING from slyp.calculations - every rate and
threshold below is typed in from GOV.UK by hand, so agreeing with the
engine means two independent derivations agree, not that one function was
called twice.

Run:  python verify/fixtures/check_estimate.py
"""
from decimal import Decimal as D

# --- 2026/27, typed from GOV.UK, not read from the engine ----------------
PERSONAL_ALLOWANCE = D("12570")          # 1257L
BASIC_RATE = D("0.20")
BASIC_BAND_TOP = D("50270")              # basic rate applies up to here
MONTHS = D("12")
NI_MONTHLY_PT = D("1048")                # primary threshold, monthly
NI_MONTHLY_UEL = D("4189")               # upper earnings limit, monthly
NI_MAIN_RATE = D("0.08")

GROSS_PER_PERIOD = D("2500")
PERIOD = D("5")
PENSION_PER_PERIOD = D("125.00")


def p(label, value):
    print(f"  {label:<52} {value:>12}")


print("=" * 68)
print("THIS PERIOD (identical in both fixtures)")
print("=" * 68)
month_allowance = PERSONAL_ALLOWANCE / MONTHS
p("one month's allowance  12,570 / 12", month_allowance)
taxable = GROSS_PER_PERIOD - month_allowance
p("taxable  2,500.00 - 1,047.50", taxable)
tax_this_period = taxable * BASIC_RATE
p("income tax  1,452.50 x 20%", tax_this_period)
assert taxable + month_allowance <= BASIC_BAND_TOP / MONTHS * 12  # basic rate only

ni = (GROSS_PER_PERIOD - NI_MONTHLY_PT) * NI_MAIN_RATE
p("NI  (2,500.00 - 1,048.00) x 8%", ni)
assert GROSS_PER_PERIOD < NI_MONTHLY_UEL  # 2% band not reached

net = GROSS_PER_PERIOD - tax_this_period - ni - PENSION_PER_PERIOD
p("net  2,500.00 - 290.50 - 116.16 - 125.00", net)
print()

for name, periods_paid in (
    ("FIXTURE A - emergency_m1_level_pay (paid since period 1)", D("5")),
    ("FIXTURE B - emergency_m1_midyear_start (started period 3)", D("3")),
):
    print("=" * 68)
    print(name)
    print("=" * 68)
    gross_ytd = GROSS_PER_PERIOD * periods_paid
    tax_paid_ytd = tax_this_period * periods_paid
    p(f"gross YTD  2,500.00 x {periods_paid}", gross_ytd)
    p(f"tax actually paid YTD under M1  290.50 x {periods_paid}", tax_paid_ytd)

    # What a cumulative 1257L would have deducted by period 5. A cumulative
    # code grants allowance by PERIOD NUMBER, not by periods worked - that
    # is the whole difference.
    cumulative_allowance = PERSONAL_ALLOWANCE * PERIOD / MONTHS
    p("cumulative allowance to period 5  12,570 x 5/12", cumulative_allowance)
    cumulative_taxable = max(D("0"), gross_ytd - cumulative_allowance)
    p("cumulative taxable  gross YTD - allowance", cumulative_taxable)
    cumulative_tax = cumulative_taxable * BASIC_RATE
    p("cumulative tax due YTD  x 20%", cumulative_tax)

    overpayment = tax_paid_ytd - cumulative_tax
    p("OVERPAYMENT  paid - cumulative-equivalent", overpayment)
    if overpayment <= 0:
        print("\n  => zero. M1 handed out one month's allowance for each month")
        print("     PAID; a cumulative code hands out one for each month")
        print("     ELAPSED. Paid every period, those are the same number, so")
        print("     M1 costs nothing. No estimate is shown, and that is correct.")
    else:
        print("\n  => a real figure: the cumulative code would have granted")
        print(f"     allowance for 5 months against {periods_paid} months of pay;")
        print("     M1 granted it for the months paid only. The unused")
        print("     allowance is what M1 costs, taxed at 20%.")
        unused = cumulative_allowance - (month_allowance * periods_paid)
        p("     unused allowance  5,237.50 - 3,142.50", unused)
        p("     x 20%", unused * BASIC_RATE)
    print()
