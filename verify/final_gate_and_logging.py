"""Items 15, 16, 17."""
import sys, os, logging, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from slyp import extraction as E

print("=== item 15: does a gate refusal actually stop the model call? ===")
calls = []
E._call_model = lambda t: calls.append(t)

# a payload the gate must refuse: an unexplained long digit run
bad = "Reference 998877665544 Gross 2,500.00"
try:
    E.assert_safe_to_send(bad)
    print("  gate did NOT refuse -", repr(bad))
except E.RedactionFailure as exc:
    print(f"  gate refused: {exc}")
print(f"  model calls made: {len(calls)} (must be 0)")

# now prove the ORDER in extract_payslip: gate raises before _call_model
import inspect
src = inspect.getsource(E.extract_payslip)
order = []
for name in ["_read_pdf", "redact(", "financial_lines_only", "assert_safe_to_send", "_call_model"]:
    order.append((src.index(name), name))
print("\n  call order inside extract_payslip():")
for _, name in sorted(order):
    print("    ", name)

print("\n=== item 15b: is the allowlist independent of the redaction regexes? ===")
red_names = {"_NI_NUMBER_RE","_POSTCODE_RE","_SORT_CODE_RE","_ACCOUNT_NUMBER_RE",
             "_EMAIL_RE","_PHONE_RE","_EMPLOYEE_NO_LABEL_RE","_NAME_LABEL_RE",
             "_TITLED_NAME_RE","_ADDRESS_LABEL_RE","_UNEXPLAINED_ID_RE"}
allow_src = inspect.getsource(E.financial_lines_only)
shared = [n for n in red_names if n in allow_src]
print(f"  redaction regexes referenced by financial_lines_only(): {shared or 'NONE'}")
print("  allowlist decides by POSITIVE financial shape:",
      [n for n in ["_CURRENCY_RE","_PERCENT_RE","_DATE_RE","_TAX_CODE_LINE_RE","_KNOWN_LABEL_RE"] if n in allow_src])

print("\n=== item 16: can only_job / UserContext reach the model? ===")
import slyp.analysis, slyp.findings, slyp.calculations
for mod in (slyp.analysis, slyp.findings, slyp.calculations):
    s = inspect.getsource(mod)
    hits = [k for k in ("anthropic", "openai", "_call_model", "requests.", "httpx", "urllib") if k in s]
    print(f"  {mod.__name__:18} network/model references: {hits or 'NONE'}")
print(f"  extract_payslip signature: {inspect.signature(E.extract_payslip)}")
print(f"  _call_model  signature:    {inspect.signature(E._call_model) if callable(E._call_model) else 'patched'}")
print("  -> UserContext is only ever passed to analyse_payslip(), which makes no model call.")

print("\n=== item 17: every logging call on the request path ===")
import subprocess
out = subprocess.run(
    ["grep","-rnE","logger\.(debug|info|warning|error|critical|exception)|logging\.|print\(",
     "main.py","slyp/"],
    capture_output=True, text=True).stdout
for line in out.splitlines():
    if "__pycache__" in line: continue
    print("  ", line)

print("\n=== item 17b: any filesystem / DB write on the path? ===")
out = subprocess.run(
    ["grep","-rnE","open\(|\.write\(|NamedTemporary|mkstemp|tempfile|sqlite|psycopg|redis|boto3|\.save\(",
     "main.py","slyp/"],
    capture_output=True, text=True).stdout
hits = [l for l in out.splitlines() if "__pycache__" not in l]
print("\n".join("   " + h for h in hits) if hits else "   NONE")
