"""Item 20: paths by which _check_net_pay raises a mismatch, and whether
the same single discrepancy is reported twice."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from decimal import Decimal
from datetime import date, datetime, timezone
from slyp.contract import (PayslipExtract, Period, TaxCodeRead, Pay, Deductions,
                           Source, UserContext)
from slyp.analysis import analyse_payslip

D = Decimal

def build(income_tax, ni, net, gross=D("3000.00"), gross_ytd=D("27000.00"),
          pension=D("0.00"), other=None, unreadable=None, reconciles=None):
    return PayslipExtract(
        source=Source(filename="x.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(pay_date=date(2026, 12, 25), period_number=9,
                      frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=gross, gross_ytd=gross_ytd),
        deductions=Deductions(income_tax=income_tax, national_insurance=ni,
                              pension_employee=pension, other=other or []),
        net_pay=net,
        unreadable_fields=unreadable or [],
        reconciles=reconciles,
    )

# Correct engine figures for gross 3000, ytd 27000, m9, 1257L cumulative:
from slyp.calculations import calculate_pay_breakdown, parse_tax_code
from slyp.types import PayPeriodFacts
f = PayPeriodFacts(gross_this_period=D("3000.00"), gross_ytd=D("27000.00"),
                   tax_code=parse_tax_code("1257L"), period_number=9,
                   frequency="monthly", ni_category="A", student_loan_plan=None)
b = calculate_pay_breakdown(f)
print(f"engine: tax={b.income_tax} ni={b.national_insurance} sl={b.student_loan}")

print("\n--- CASE A: payslip correct, reconciles True -> expect NO findings ---")
correct_net = D("3000.00") - b.income_tax - b.national_insurance
e = build(b.income_tax, b.national_insurance, correct_net, reconciles=True)
r = analyse_payslip(e, UserContext(only_job=True))
print("  findings:", [(f_.id, f_.severity) for f_ in r.findings])
print("  verdict :", r.verdict.headline, "| score", r.score.value, f"({r.score.checks_passed}/{r.score.checks_run})")

print("\n--- CASE B: ONE wrong figure (income tax £50 too low), payslip self-consistent ---")
wrong_tax = b.income_tax - D("50.00")
net_b = D("3000.00") - wrong_tax - b.national_insurance
e = build(wrong_tax, b.national_insurance, net_b, reconciles=True)
r = analyse_payslip(e, UserContext(only_job=True))
for f_ in r.findings:
    est = f"  £{f_.estimate.amount_gbp}" if f_.estimate else ""
    print(f"  {f_.severity:8} {f_.id}{est}")
print("  verdict :", r.verdict.headline, "| score", r.score.value, f"({r.score.checks_passed}/{r.score.checks_run})")
print("  >>> ONE underpayment of £50; how many action findings? ",
      sum(1 for f_ in r.findings if f_.severity == "action"))

print("\n--- CASE C: reconciles False (does not add up) -> expected_net must be None ---")
e = build(b.income_tax, b.national_insurance, D("1.00"), reconciles=False)
r = analyse_payslip(e, UserContext(only_job=True))
print("  findings:", [f_.id for f_ in r.findings])
print("  net_pay finding present?", any(f_.id == "net_pay_differs_from_calculation" for f_ in r.findings))

print("\n--- CASE D: reconciles None -> expected_net must be None ---")
e = build(b.income_tax, b.national_insurance, D("1.00"), reconciles=None)
r = analyse_payslip(e, UserContext(only_job=True))
print("  net_pay finding present?", any(f_.id == "net_pay_differs_from_calculation" for f_ in r.findings))

print("\n--- CASE E: pension unreadable -> expected_net must be None ---")
e = build(b.income_tax, b.national_insurance, D("1.00"), pension=D("100.00"),
          unreadable=["deductions.pension_employee"], reconciles=True)
r = analyse_payslip(e, UserContext(only_job=True))
print("  net_pay finding present?", any(f_.id == "net_pay_differs_from_calculation" for f_ in r.findings))

print("\n--- CASE F: 'other' deduction present and counted ---")
from slyp.contract import OtherDeduction
other = [OtherDeduction(type="union", amount=D("12.00"))]
net_f = D("3000.00") - b.income_tax - b.national_insurance - D("12.00")
e = build(b.income_tax, b.national_insurance, net_f, other=other, reconciles=True)
r = analyse_payslip(e, UserContext(only_job=True))
print("  net_pay finding present?", any(f_.id == "net_pay_differs_from_calculation" for f_ in r.findings),
      "(should be False - 'other' must be subtracted)")
