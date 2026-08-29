"""
Items 13, 14, 16: build a synthetic payslip carrying every PII shape the
brief names, run the REAL extract_payslip(), intercept the exact string
that reaches the model, and assert each PII item is absent and each date
survives.

No real payslip is used. Every value below is invented.
"""
from __future__ import annotations
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slyp import extraction
from slyp.extraction import extract_payslip, RedactionFailure

# ---------------------------------------------------------------- fixture
def _pdf(lines):
    ops = ["BT", "/F1 10 Tf", "20 800 Td"]
    for line in lines:
        esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops += [f"({esc}) Tj", "0 -13 Td"]
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


PII = {
    "name (labelled)":        "Jonathan Ashworth-Pike",
    "name (titled, inline)":  "Mr J ASHWORTH",
    "address line":           "14 Marlborough Crescent, Leeds",
    "postcode":               "LS7 4QT",
    "NI spaced":              "AB 12 34 56 C",
    "NI unspaced":            "JK654321B",
    "NI periods":             "AB.98.76.54.A",
    "NI lowercase":           "eh 65 43 21 d",
    "sort code spaces":       "20 45 67",
    "sort code dashes":       "30-96-12",
    "sort code slashes":      "40/12/78",
    "account number":         "51234567",
    "employee number":        "8842176",
    "email":                  "j.ashworth@example.co.uk",
    "phone":                  "07700 900123",
}

DATES = {
    "DD/MM/YYYY": "28/08/2026",
    "DD-MM-YYYY": "31-07-2026",
    "D/M/YY":     "5/8/26",
    "YYYY-MM-DD": "2026-08-28",
}

LINES = [
    "Employer: Northwind Trading Ltd",
    f"Employee Name: {PII['name (labelled)']}",
    f"Address: {PII['address line']} {PII['postcode']}",
    f"Employee No: {PII['employee number']}   Pay Date: {DATES['DD/MM/YYYY']}",
    # NI number sharing a line with a currency amount - the ordering hazard
    f"NI Number {PII['NI spaced']}     National Insurance 116.16",
    f"NI Ref {PII['NI unspaced']}      Income Tax 290.50",
    f"Alt NI {PII['NI periods']}       Employee Pension 125.00",
    f"Prev NI {PII['NI lowercase']}    Gross 2,500.00",
    # a date ADJACENT TO an account number on the same line (brief item 14)
    f"Account {PII['account number']} paid {DATES['DD-MM-YYYY']} Net Pay 1,968.34",
    f"Sort Code {PII['sort code spaces']}   Sort {PII['sort code dashes']}   Sort {PII['sort code slashes']}",
    f"Period ending {DATES['D/M/YY']}   Tax Period: 5   Payment Period Monthly",
    f"Processed {DATES['YYYY-MM-DD']}   Tax Code: 1257L M1   NI Table Letter A",
    f"{PII['name (titled, inline)']} 2,500.00",
    f"Contact {PII['email']}  Tel {PII['phone']}",
    "Total Gross Pay 2,500.00     Net Pay 1,968.34",
    "Gross Pay YTD 7,500.00       Income Tax YTD 871.50",
]

captured = {}

def _fake_call(filtered_text):
    captured["payload"] = filtered_text
    raise SystemExit("__INTERCEPTED__")

extraction._call_model = _fake_call

pdf = _pdf(LINES)
gate_refused = None
try:
    extract_payslip(pdf, filename="synthetic.pdf")
except SystemExit:
    pass
except RedactionFailure as exc:
    gate_refused = str(exc)

print("=" * 74)
if gate_refused:
    print(f"GATE REFUSED before the model call: {gate_refused}")
    print("=> nothing was sent. Re-running with the gate observed separately.")
    text = extraction.extract_text(pdf)
    red, _ = extraction.redact(text)
    payload = extraction.financial_lines_only(red)
else:
    payload = captured.get("payload")

if payload is None:
    print("NO PAYLOAD CAPTURED"); sys.exit(1)

print("ACTUAL PAYLOAD THAT WOULD REACH THE MODEL")
print("=" * 74)
print(payload)
print("=" * 74)

print("\n--- item 13: is each PII value absent from the payload? ---")
leaks = []
for label, value in PII.items():
    # search case-insensitively, and also with separators stripped, so a
    # partially-redacted remnant still counts as a leak
    bare = re.sub(r"[^A-Za-z0-9]", "", value).lower()
    payload_bare = re.sub(r"[^A-Za-z0-9]", "", payload).lower()
    present = value.lower() in payload.lower() or (len(bare) >= 6 and bare in payload_bare)
    status = "LEAKED" if present else "absent"
    if present:
        leaks.append(label)
    print(f"  {status:8} {label:24} {value!r}")

print("\n--- item 14: does each date survive redaction intact? ---")
lost = []
for label, value in DATES.items():
    present = value in payload
    if not present:
        lost.append(label)
    print(f"  {'INTACT' if present else 'DESTROYED':10} {label:12} {value!r}")

print("\n--- item 15: does the gate pass this payload? ---")
try:
    extraction.assert_safe_to_send(payload)
    print("  gate: PASSED (no PII pattern matched)")
except RedactionFailure as exc:
    print(f"  gate: REFUSED - {exc}")

print("\n" + "=" * 74)
print(f"RESULT: {len(leaks)} PII leak(s), {len(lost)} date(s) destroyed")
if leaks: print("  leaked:", leaks)
if lost:  print("  lost  :", lost)
