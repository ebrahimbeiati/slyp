"""Item 9 + 10: does the engine refuse rather than approximate?"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from decimal import Decimal
from slyp.calculations import (
    parse_tax_code, income_tax_due, annual_income_tax,
    cumulative_income_tax_due, non_cumulative_income_tax_due,
    validate_tax_year, personal_allowance_for_income,
)
from slyp.types import PayPeriodFacts, UnsupportedPayslip

print("=== item 9: tax code refusals ===")
for code in ["S1257L", "C1257L", "K475", "1257L", "ZZZZ", "", "  ", "12X7Q"]:
    try:
        tc = parse_tax_code(code)
        print(f"  {code!r:10} -> PARSED kind={tc.kind} free_pay={tc.free_pay_annual}")
    except UnsupportedPayslip as e:
        print(f"  {code!r:10} -> REFUSED UnsupportedPayslip: {e}")
    except Exception as e:
        print(f"  {code!r:10} -> {type(e).__name__}: {e}")

print("\n=== item 9: tax year refusals ===")
for ty in ["2025/26", "2026/27", "2019/20", "2099/00", None, "garbage"]:
    try:
        validate_tax_year(ty)
        print(f"  {ty!r:10} -> ACCEPTED")
    except UnsupportedPayslip as e:
        print(f"  {ty!r:10} -> REFUSED: {e}")
    except Exception as e:
        print(f"  {ty!r:10} -> {type(e).__name__}: {e}")

print("\n=== item 10: the 100k taper ===")
tc = parse_tax_code("1257L")
# monthly, period 12, annual gross 150,000 -> 12,500/month
facts = PayPeriodFacts(
    gross_this_period=Decimal("12500.00"),
    gross_ytd=Decimal("150000.00"),
    tax_code=tc,
    period_number=12,
    frequency="monthly",
    ni_category="A",
    student_loan_plan=None,
)
print("  personal_allowance_for_income(150000) =", personal_allowance_for_income(Decimal("150000")))
print("  -> correct tapered allowance is 0")
try:
    v = annual_income_tax(Decimal("150000"), tc)
    print(f"  annual_income_tax(150000)        -> RETURNED {v}   *** no refusal ***")
except UnsupportedPayslip as e:
    print(f"  annual_income_tax(150000)        -> REFUSED: {e}")

for name, fn in [("income_tax_due", income_tax_due),
                 ("cumulative_income_tax_due", cumulative_income_tax_due)]:
    try:
        v = fn(facts)
        print(f"  {name:26} -> RETURNED £{v}   *** no refusal ***")
    except UnsupportedPayslip as e:
        print(f"  {name:26} -> REFUSED: {e}")
    except Exception as e:
        print(f"  {name:26} -> {type(e).__name__}: {e}")

from dataclasses import replace as dc_replace
m1 = dc_replace(tc, cumulative=False)
facts_m1 = dc_replace(facts, tax_code=m1)
try:
    v = non_cumulative_income_tax_due(facts_m1)
    print(f"  {'non_cumulative_income_tax_due':26} -> RETURNED £{v}   *** no refusal ***")
except UnsupportedPayslip as e:
    print(f"  {'non_cumulative_income_tax_due':26} -> REFUSED: {e}")

print("\n  What the engine's own tapered-allowance helper implies is correct:")
print("   taxable with 0 allowance   = 150000")
print("   correct annual tax         = 20%*37700 + 40%*(125140-37700) + 45%*(150000-125140)")
correct = Decimal("37700")*Decimal("0.20") + (Decimal("125140")-Decimal("37700"))*Decimal("0.40") + (Decimal("150000")-Decimal("125140"))*Decimal("0.45")
print(f"                              = £{correct}")
