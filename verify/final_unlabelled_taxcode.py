"""
Why an unlabelled tax code comes back unreadable.

Reported shape, seen on two real payslips:

    NI No:        NI Rate:M        1257L        Month No:5

Four label/value pairs collapsed onto one line, the NI number blank, and
the tax code sitting between "NI Rate:M" and "Month No:5" with nothing
identifying it as a tax code.

Runs the same payslip twice - once with that line, once with an explicit
"Tax Code:" label and nothing else changed - so the only variable is the
label. Repeats each to separate a hard failure from model variance.

Synthetic throughout. No real payslip is used.
"""
from __future__ import annotations

import io
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from slyp import extraction as E  # noqa: E402

RUNS = int(os.environ.get("RUNS", "3"))


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


def payslip(code_line):
    return _pdf([
        "Employer: Northwind Trading Ltd",
        "Employee Name: Mr K Sample",
        code_line,
        "Pay Date: 28/08/2026",
        "",
        "Payments                        Deductions",
        "Basic Pay 2,500.00              Income Tax 290.50",
        "                                National Insurance 116.16",
        "",
        "Total Gross Pay 2,500.00        Net Pay 2,093.34",
        "",
        "Year to date",
        "Gross Pay YTD 12,500.00         Income Tax YTD 1,452.50",
        "                                National Insurance YTD 580.80",
    ])


CASES = [
    ("UNLABELLED - the reported shape",
     "NI No:        NI Rate:M        1257L        Month No:5"),
    ("LABELLED control - only difference",
     "NI No:        NI Rate:M        Tax Code: 1257L        Month No:5"),
    ("labelled, own line",
     "Tax Code: 1257L     NI Table Letter A"),
    # The unlabelled line reads fine, so the cause is elsewhere. These
    # probe _TAX_CODE_RE, the validator extract_payslip runs over whatever
    # the model returns - a shape it rejects is silently marked unreadable
    # with no warning saying the code was read and then thrown away.
    ("collapsed: NI Rate:M welded to the code",
     "NI No: NI Rate:M1257L Month No:5"),
    ("basis spelled out rather than M1",
     "NI No:   NI Rate:M   1257L Cumul   Month No:5"),
    ("space inside the code",
     "NI No:   NI Rate:M   1257 L   Month No:5"),
]

print("=" * 78)
print(f"UNLABELLED TAX CODE - {RUNS} run(s) per case")
print("=" * 78)

for label, code_line in CASES:
    print(f"\n{label}")
    print(f"  line: {code_line!r}")

    # What the model is actually shown.
    text = E.extract_text(payslip(code_line))
    redacted, _ = E.redact(text)
    filtered = E.financial_lines_only(redacted)
    # "1257" not "1257L": a code printed as "1257 L" still reaches the
    # model, and checking for the joined form reported it as dropped when
    # it was not.
    kept = [l for l in filtered.splitlines() if "1257" in l]
    print(f"  line survives to the model: {bool(kept)}")
    if kept:
        print(f"    as: {kept[0].strip()!r}")

    values, confidences, unreadable = Counter(), [], 0
    for _ in range(RUNS):
        try:
            extract = E.extract_payslip(payslip(code_line), filename="t.pdf")
        except Exception as exc:
            values[f"<{type(exc).__name__}>"] += 1
            continue
        values[str(extract.tax_code.value)] += 1
        conf = extract.confidence.get("tax_code.value")
        if conf is not None:
            confidences.append(conf)
        if "tax_code.value" in extract.unreadable_fields:
            unreadable += 1

    print(f"  tax_code.value over {RUNS} run(s): {dict(values)}")
    print(f"  confidence reported            : {confidences or 'none'}")
    print(f"  flagged unreadable             : {unreadable}/{RUNS}")
