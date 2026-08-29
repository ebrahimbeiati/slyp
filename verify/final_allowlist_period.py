"""Items 21 and 22."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from slyp import extraction as E

print("=== item 21: does the allowlist KEEP each label line (no currency on it)? ===")
lines = [
  ("frequency (word)",        "Pay Frequency Monthly"),
  ("payment period",          "Payment Period    Weekly"),
  ("pay period",              "Pay Period Monthly"),
  ("pay type",                "Pay Type Salaried"),
  ("pay basis",               "Pay Basis Monthly"),
  ("tax period",              "Tax Period 9"),
  ("tax month",               "Tax Month 9"),
  ("tax week",                "Tax Week 39"),
  ("period number",           "Period Number 9"),
  ("NI category",             "NI Category A"),
  ("NI table",                "NI Table B"),
  ("table letter",            "Table Letter A"),
  ("postgraduate loan",       "Postgraduate Loan"),
  ("PGL",                     "PGL Plan"),
  ("student loan",            "Student Loan Plan 2"),
  ("pay date label",          "Pay Date 28 August 2026"),
  ("pay day label",           "Pay Day Friday"),
  ("payment date label",      "Payment Date 28/08/2026"),
  ("date of payment",         "Date of Payment 28/08/2026"),
  ("tax code",                "Tax Code 1257L"),
  # negative controls - these SHOULD be dropped
  ("[-] bare name line",      "Jonathan Ashworth-Pike"),
  ("[-] bare address",        "14 Marlborough Crescent"),
  ("[-] section header",      "Deductions"),
  ("[-] payments header",     "Payments"),
]
for label, line in lines:
    kept = E.financial_lines_only(line).strip() != ""
    expect_drop = label.startswith("[-]")
    ok = (not kept) if expect_drop else kept
    mark = "ok " if ok else "**"
    print(f"  {mark} {'KEPT ' if kept else 'DROPPED'}  {label:22} {line!r}")

print("\n=== item 22: period number - derived wins, label fallback is bounded ===")
print("  derive_period_number(pay_date, frequency):")
for d, f, exp in [
    (date(2026,8,28), "monthly", 5), (date(2026,4,6),  "monthly", 1),
    (date(2026,4,5),  "monthly", 12), (date(2027,4,5), "monthly", 12),
    (date(2026,5,3),  "monthly", 1),  (date(2026,5,6), "monthly", 2),
    (date(2026,4,6),  "weekly", 1),   (date(2026,4,12),"weekly", 1),
    (date(2026,4,13), "weekly", 2),   (date(2027,4,5), "weekly", 53),
]:
    got = E.derive_period_number(d, f)
    print(f"    {d} {f:8} -> {got}  {'ok' if got==exp else f'** expected {exp}'}")
print(f"    (None, 'monthly') -> {E.derive_period_number(None,'monthly')}  (must be None)")
print(f"    (date, None)      -> {E.derive_period_number(date(2026,8,28),None)}  (must be None)")

print("\n  _period_number_plausible (bounds the printed-label fallback):")
for n, f in [(9,"monthly"),(13,"monthly"),(0,"monthly"),(39,"weekly"),(54,"weekly"),(9,None)]:
    print(f"    period {n:3} against {str(f):8} -> {E._period_number_plausible(n, f)}")

print("\n  infer_frequency_from_label:")
for t in ["Tax Month 9","Month 9","Week 39","Payment Period Weekly","Monthly",
          "Period 9","Week Ending 15/12/2025","Fortnightly","4-Weekly"]:
    print(f"    {t!r:28} -> {E.infer_frequency_from_label(t)!r}")

print("\n  read_pay_date_from_label:")
for t in ["Pay Date: 28/08/2026","Pay Date 28-08-2026","Payment Date 2026-08-28",
          "Pay Date 28 August 2026","Pay Day Friday","Date of Payment 28/08/2026"]:
    print(f"    {t!r:34} -> {E.read_pay_date_from_label(t)!r}")
