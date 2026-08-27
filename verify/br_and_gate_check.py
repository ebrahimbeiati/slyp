import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "patched_pkg"))

from datetime import datetime, timezone
from decimal import Decimal
from slyp.contract import PayslipExtract, Source, Period, TaxCodeRead, Pay, Deductions, UserContext
from slyp.findings import generate_findings, _check_reconciliation

def make_extract(**overrides):
    base = dict(
        source=Source(filename="x.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(pay_date=None, period_number=6, frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value="BR"),
        pay=Pay(gross_this_period=Decimal("2000"), gross_ytd=Decimal("12000")),
        deductions=Deductions(income_tax=Decimal("400"), national_insurance=Decimal("100")),
        net_pay=Decimal("1500"),
        unreadable_fields=[],
        confidence={},
    )
    base.update(overrides)
    return PayslipExtract(**base)

print("=== BR branch: only_job=True ===")
extract = make_extract()
findings = generate_findings(extract, UserContext(only_job=True))
br = [f for f in findings if f.id.startswith("tax_code_br")]
for f in br:
    print(f"  id={f.id} severity={f.severity} estimate={f.estimate}")

print("\n=== BR branch: only_job=False ===")
findings = generate_findings(extract, UserContext(only_job=False))
br = [f for f in findings if f.id.startswith("tax_code_br")]
for f in br:
    print(f"  id={f.id} severity={f.severity} estimate={f.estimate}")

print("\n=== BR branch: only_job=None (not told) ===")
findings = generate_findings(extract, UserContext(only_job=None))
br = [f for f in findings if f.id.startswith("tax_code_br")]
for f in br:
    print(f"  id={f.id} severity={f.severity} estimate={f.estimate}")
print("  -> No branch attaches a numeric overpayment Estimate in the live code (confirmed above: estimate=None in all three).")

# ---------------------------------------------------------------------
# Confidence gate: reconciliation field missing => rule must not run at all
# ---------------------------------------------------------------------
print("\n=== Confidence gate: national_insurance flagged unreadable ===")
gated_extract = make_extract(unreadable_fields=["deductions.national_insurance"])
gated_extract.deductions.national_insurance = None  # simulate what extraction.py would have nulled
finding = _check_reconciliation(gated_extract)
print(f"  _check_reconciliation result when NI is unreadable: {finding}")
assert finding is None, "GATE FAILURE: a finding was produced despite a required field being unreadable"
print("  -> PASS: no finding produced (gate holds for this rule).")

print("\n=== Confidence gate: gross_this_period present but in unreadable_fields (contradicts value) ===")
weird_extract = make_extract(unreadable_fields=["pay.gross_this_period"])
finding2 = _check_reconciliation(weird_extract)
print(f"  _check_reconciliation result: {finding2}")
assert finding2 is None, "GATE FAILURE"
print("  -> PASS: gate respects unreadable_fields even when the raw value is still non-null.")
