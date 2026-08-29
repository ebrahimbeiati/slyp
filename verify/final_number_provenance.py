"""Item 6: every numeric value in the API response, traced to its origin."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

live = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_live_results.json")))
result = live["emergency_only_job"]

# Origin of every field that can hold a number, by JSON path prefix.
# MODEL  = the model read it off the (redacted) document
# CODE   = computed in Python
# FILE   = metadata about the upload
ORIGIN = {
  "extract.source.pages":                      ("FILE",  "len(pdf.pages), extraction._read_pdf"),
  "extract.period.period_number":              ("CODE",  "derive_period_number() - arithmetic from pay_date"),
  "extract.period.pay_date":                   ("MODEL", "read off the document (or read_pay_date_from_label)"),
  "extract.period.tax_year":                   ("CODE",  "_tax_year_for(pay_date) - 6 April boundary"),
  "extract.pay.hourly_rate":                   ("MODEL", "read off the document"),
  "extract.pay.hours":                         ("MODEL", "read off the document"),
  "extract.pay.gross_this_period":             ("MODEL", "read off the document"),
  "extract.pay.gross_ytd":                     ("MODEL", "read off the document"),
  "extract.deductions.income_tax":             ("MODEL", "read off the document"),
  "extract.deductions.income_tax_ytd":         ("MODEL", "read off the document"),
  "extract.deductions.national_insurance":     ("MODEL", "read off the document"),
  "extract.deductions.national_insurance_ytd": ("MODEL", "read off the document"),
  "extract.deductions.pension_employee":       ("MODEL", "read off the document"),
  "extract.deductions.pension_employer":       ("MODEL", "read off the document"),
  "extract.deductions.pension_percent":        ("MODEL", "read off the document"),
  "extract.deductions.student_loan":           ("MODEL", "read off the document"),
  "extract.confidence.*":                      ("MODEL", "self-reported confidence (never shown as money)"),
  "score.value":                               ("CODE",  "analysis.build_score()"),
  "score.checks_passed":                       ("CODE",  "analysis.build_score()"),
  "score.checks_run":                          ("CODE",  "analysis.build_score()"),
  "findings[].estimate.amount_gbp":            ("CODE",  "findings._emergency_code_overpayment_amount()"),
}

def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[]")
    else:
        yield path, node

def is_numeric(v):
    if isinstance(v, bool) or v is None: return False
    if isinstance(v, (int, float)): return True
    if isinstance(v, str):
        try: float(v.replace(",", "")); return True
        except ValueError: return False
    return False

print("=" * 96)
print(f"{'PATH':52} {'VALUE':>12}  ORIGIN")
print("=" * 96)
seen = {}
for path, value in walk(result):
    if not is_numeric(value): continue
    key = path
    if key.startswith("extract.confidence."): key = "extract.confidence.*"
    origin, how = ORIGIN.get(key, ("UNKNOWN", "!! not classified !!"))
    seen.setdefault(key, []).append((path, value))
    print(f"{path:52} {str(value):>12}  {origin:6} {how}")

print("=" * 96)
model_money = [k for k in seen if ORIGIN.get(k, ("UNKNOWN",))[0] == "MODEL"]
unknown = [k for k in seen if ORIGIN.get(k, ("UNKNOWN",))[0] == "UNKNOWN"]
print(f"\nunclassified numeric fields: {unknown or 'none'}")
print(f"""
VERDICT for Rule 1:
  Numbers the MODEL supplies are TRANSCRIPTIONS of what is printed on the
  payslip ({len(model_money)} such fields). The model performs no arithmetic:
  its schema (_ModelExtract) has no field for reconciles, tax_year, or any
  computed figure, so there is nothing for it to calculate into.

  Every DERIVED number - the score, the checks, the overpayment estimate,
  the tax year, the period number, and every expected-vs-actual comparison -
  is computed in Python.

  The one number the user reads as a RESULT (estimate.amount_gbp) is
  computed by findings._emergency_code_overpayment_amount() from
  calculations.cumulative_tax_due_to_date().""")
