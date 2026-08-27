"""
What every fixture renders for the Personal-Allowance-used figure.

Runs the four committed fixtures through the LIVE API, plus a synthetic
weekly payslip and a synthetic previous-employment payslip generated here
(no real payslip is used anywhere in this repo).

Each is run on both branches of the other-employment question, because the
gate is the point: only "no other employment" gets a figure.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("SLYP_TEST_BASE", "http://127.0.0.1:8070")


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
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


# A weekly payslip. Figures are internally consistent and match what the
# engine expects for 1257L cumulative at week 20 on GBP 480/wk, so the only
# thing under test is the allowance figure.
WEEKLY = _pdf([
    "Employer: Northwind Trading Ltd",
    "Employee Name: A Sample",
    "Pay Date: 21/08/2026",
    "Tax Week: 20     Payment Period Weekly",
    "Tax Code: 1257L     NI Table Letter A",
    "",
    "Basic Pay 480.00              Income Tax 47.66",
    "                              National Insurance 19.04",
    "",
    "Total Gross Pay 480.00        Net Pay 413.30",
    "",
    "Year to date",
    "Gross Pay YTD 9,600.00        Income Tax YTD 953.20",
    "                              National Insurance YTD 380.80",
])

# The same weekly payslip, but printing a P45 carry-forward from an earlier
# job. Everything else is identical, so any difference in output is the
# previous-employment guard and nothing else.
WEEKLY_WITH_PREVIOUS = _pdf([
    "Employer: Northwind Trading Ltd",
    "Employee Name: A Sample",
    "Pay Date: 21/08/2026",
    "Tax Week: 20     Payment Period Weekly",
    "Tax Code: 1257L     NI Table Letter A",
    "",
    "Basic Pay 480.00              Income Tax 47.66",
    "                              National Insurance 19.04",
    "",
    "Total Gross Pay 480.00        Net Pay 413.30",
    "",
    "Year to date",
    "Gross Pay YTD 9,600.00        Income Tax YTD 953.20",
    "                              National Insurance YTD 380.80",
    "",
    "Previous Employment (P45)     Gross 4,200.00",
])


def post(pdf_bytes, only_job):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()

    def part(header, data):
        body.write(f"--{boundary}\r\n{header}\r\n\r\n".encode())
        body.write(data)
        body.write(b"\r\n")

    part('Content-Disposition: form-data; name="file"; filename="p.pdf"\r\n'
         "Content-Type: application/pdf", pdf_bytes)
    if only_job is not None:
        part('Content-Disposition: form-data; name="only_job"',
             str(only_job).lower().encode())
    body.write(f"--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"{BASE}/analyse", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return {"status": f"HTTP {exc.code}", "detail": exc.read()[:120].decode("utf-8", "replace")}


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), "rb") as handle:
        return handle.read()


CASES = [
    ("emergency M1 mid-year start", fixture("emergency_m1_midyear_start.pdf")),
    ("emergency M1 level pay", fixture("emergency_m1_level_pay.pdf")),
    ("BR second job", fixture("br_second_job.pdf")),
    ("under all thresholds", fixture("under_all_thresholds.pdf")),
    ("weekly, synthetic", WEEKLY),
    ("weekly + previous employment, synthetic", WEEKLY_WITH_PREVIOUS),
]

ANSWERS = [(True, "no other job"), (False, "had another job"), (None, "not sure")]

print("=" * 96)
print("PERSONAL ALLOWANCE USED - what each fixture renders")
print("=" * 96)

for label, pdf_bytes in CASES:
    print(f"\n{label}")
    for only_job, answer in ANSWERS:
        payload = post(pdf_bytes, only_job)
        usage = payload.get("allowance_usage")
        extract = payload.get("extract") or {}
        code = (extract.get("tax_code") or {}).get("value")
        ytd = (extract.get("pay") or {}).get("gross_ytd")
        prev = extract.get("previous_employment_ytd_present")
        if payload.get("status") != "ok":
            shown = f"(status {payload['status']})"
        elif usage:
            shown = usage["statement"]
        else:
            shown = "- nothing rendered -"
        flag = " [prev-employment line found]" if prev else ""
        print(f"    {answer:16} code={str(code):9} ytd={str(ytd):>10}  {shown}{flag}")
