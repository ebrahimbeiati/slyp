"""
Independent hand-calculation check against the LIVE calculations.py
functions (via the import-bug-patched copy in verify/patched_pkg), per
verification-prompt.md Phase 5 item 27.

This does NOT touch slyp/ source. It imports the patched scratch copy.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "patched_pkg"))

from decimal import Decimal
from slyp.calculations import (
    parse_tax_code, cumulative_income_tax_due, national_insurance_due,
    student_loan_due,
)
from slyp.types import PayPeriodFacts

# ---------------------------------------------------------------------
# Case 1: 1257L, monthly, period 6, flat £3,000/month
# ---------------------------------------------------------------------
tax_code = parse_tax_code("1257L")
facts = PayPeriodFacts(
    gross_this_period=Decimal("3000"),
    gross_ytd=Decimal("18000"),
    tax_code=tax_code,
    period_number=6,
    frequency="monthly",
    ni_category="A",
)
tax = cumulative_income_tax_due(facts)
ni = national_insurance_due(Decimal("3000"), "monthly", "A")
sl = student_loan_due(Decimal("3000"), "monthly", "2")

print("=== Case 1: 1257L monthly, period 6, £3,000/period flat, plan 2 loan ===")
print(f"  income tax  (code) = {tax}   (hand calc expected 390.50)")
print(f"  NI          (code) = {ni}   (hand calc expected 156.16)")
print(f"  student loan(code) = {sl}   (hand calc expected 49)")
assert tax == Decimal("390.50"), f"TAX MISMATCH: {tax}"
assert ni == Decimal("156.16"), f"NI MISMATCH: {ni}"
assert sl == Decimal("49"), f"STUDENT LOAN MISMATCH: {sl}"
print("  -> Case 1 MATCHES hand calculation.\n")

# ---------------------------------------------------------------------
# Case 2: BR, weekly, period 1, £1,200/week
# ---------------------------------------------------------------------
tax_code2 = parse_tax_code("BR")
facts2 = PayPeriodFacts(
    gross_this_period=Decimal("1200"),
    gross_ytd=Decimal("1200"),
    tax_code=tax_code2,
    period_number=1,
    frequency="weekly",
    ni_category="A",
)
tax2 = cumulative_income_tax_due(facts2)
ni2 = national_insurance_due(Decimal("1200"), "weekly", "A")

print("=== Case 2: BR weekly, period 1, £1,200 ===")
print(f"  income tax  (code) = {tax2}   (hand calc expected 240.00)")
print(f"  NI          (code) = {ni2}   (hand calc expected 62.66)")
assert tax2 == Decimal("240.00"), f"TAX MISMATCH: {tax2}"
assert ni2 == Decimal("62.66"), f"NI MISMATCH: {ni2}"
print("  -> Case 2 MATCHES hand calculation.\n")

print("ALL HAND CALCULATIONS MATCH THE LIVE (patched-import-only) calculations.py OUTPUT.")
