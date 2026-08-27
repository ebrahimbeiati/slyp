"""
Synthetic payslip fixtures — NOT derived from any real payslip.

Every figure here is invented and hand-checked (see check_estimate.py for
the arithmetic). No real name, employer, NI number, address or account
number appears in this file or in the PDFs it writes.

Two fixtures, because the obvious one does not do what it looks like it
does:

  emergency_m1_level_pay.pdf
      1257L M1, monthly, period 5, £2,500/period, paid every period since
      period 1. This is the fixture the demo brief asked for. Its
      overpayment estimate is EXACTLY ZERO, and that is correct: with
      level pay and the same code all year, M1 hands out one month's
      allowance five times (5 x £1,047.50 = £5,237.50) and a cumulative
      code hands out five months' allowance (£12,570 x 5/12 = £5,237.50).
      The same number. M1 only costs money when some of the cumulative
      allowance would otherwise go unused.

  emergency_m1_midyear_start.pdf
      The same payslip for someone who STARTED in period 3 - three
      payments, £7,500 YTD, at period 5. Now the cumulative code would
      grant five months of allowance against three months of pay, M1
      grants three, and the gap is real money: £419.00.

  br_second_job.pdf
      BR, £476/month, £95.20 tax, £0 NI. Under the monthly primary
      threshold, so the NI check has £0.00 expected against £0.00 actual
      and must report as not applicable rather than as a pass.

  under_all_thresholds.pdf
      1257L, £583.55/month. Under the personal allowance AND the primary
      threshold, so BOTH deduction checks are vacuous. This is the
      payslip that used to report "4/4 checks clear" having verified
      nothing.

All four are exercised together by verify/run_regression.py.

Run:  python verify/fixtures/make_fixtures.py
"""
from __future__ import annotations

import os
import sys

FIXTURE_DIR = os.path.dirname(os.path.abspath(__file__))


def _make_pdf_bytes(lines: list[str]) -> bytes:
    """
    Minimal single-page PDF with `lines` as a real text layer. Same
    approach as tests/test_extraction.py's helper (no PDF-authoring
    library is a project dependency); duplicated rather than imported so
    verify/ never depends on tests/.
    """
    content_ops = ["BT", "/F1 11 Tf", "20 780 Td"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_ops.append(f"({escaped}) Tj")
        content_ops.append("0 -14 Td")
    content_ops.append("ET")
    content = " ".join(content_ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 600 800] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (f"<< /Length {len(content)} >>\nstream\n".encode("latin-1"))
        + content
        + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n"
        f"{xref_at}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)


def _payslip_lines(
    *,
    gross_ytd: str,
    tax_ytd: str,
    ni_ytd: str,
    pension_ytd: str,
) -> list[str]:
    """
    One period's figures are identical across both fixtures; only the
    year-to-date column differs. Columns are written collapsed onto one
    line the way pdfplumber returns them from a real payslip (see
    extraction.py's module docstring).
    """
    return [
        "Employer: Northwind Trading Ltd",
        "Employee Name: A Sample",
        "Works Number: 4471",
        "Pay Date: 28/08/2026",
        "Tax Period: 5     Payment Period Monthly",
        "Tax Code: 1257L M1     NI Table Letter A",
        "",
        "Payments                        Deductions",
        "Basic Pay 2,500.00              Income Tax 290.50",
        "                                National Insurance 116.16",
        "                                Employee Pension 125.00",
        "",
        "Total Gross Pay 2,500.00        Net Pay 1,968.34",
        "",
        "Year to date",
        f"Gross Pay YTD {gross_ytd}          Income Tax YTD {tax_ytd}",
        f"                                National Insurance YTD {ni_ytd}",
        f"                                Employee Pension YTD {pension_ytd}",
    ]


def _simple_lines(*, tax_code, gross, tax, ni, net, gross_ytd, tax_ytd, ni_ytd):
    """A shorter payslip than the emergency pair - no pension line. Used
    by the two threshold fixtures, where what matters is which checks can
    run at all, not the deduction mix."""
    return [
        "Employer: Northwind Trading Ltd",
        "Employee Name: A Sample",
        "Pay Date: 28/08/2026",
        "Tax Period: 5     Payment Period Monthly",
        f"Tax Code: {tax_code}     NI Table Letter A",
        "",
        f"Basic Pay {gross}              Income Tax {tax}",
        f"                                National Insurance {ni}",
        "",
        f"Total Gross Pay {gross}        Net Pay {net}",
        "",
        "Year to date",
        f"Gross Pay YTD {gross_ytd}      Income Tax YTD {tax_ytd}",
        f"                                National Insurance YTD {ni_ytd}",
    ]


FIXTURES = {
    # Brief's spec: paid every period since period 1. 5 x 2,500 = 12,500.
    "emergency_m1_level_pay.pdf": _payslip_lines(
        gross_ytd="12,500.00",
        tax_ytd="1,452.50",
        ni_ytd="580.80",
        pension_ytd="625.00",
    ),
    # Started in period 3: three payments by period 5. 3 x 2,500 = 7,500.
    "emergency_m1_midyear_start.pdf": _payslip_lines(
        gross_ytd="7,500.00",
        tax_ytd="871.50",
        ni_ytd="348.48",
        pension_ytd="375.00",
    ),
    # BR on a second job: income tax is real (£95.20), NI is not.
    "br_second_job.pdf": _simple_lines(
        tax_code="BR",
        gross="476.00",
        tax="95.20",
        ni="0.00",
        net="380.80",
        gross_ytd="2,380.00",
        tax_ytd="476.00",
        ni_ytd="0.00",
    ),
    # Under everything: neither deduction check has anything to compare.
    "under_all_thresholds.pdf": _simple_lines(
        tax_code="1257L",
        gross="583.55",
        tax="0.00",
        ni="0.00",
        net="583.55",
        gross_ytd="854.07",
        tax_ytd="0.00",
        ni_ytd="0.00",
    ),
}


def main() -> int:
    for name, lines in FIXTURES.items():
        path = os.path.join(FIXTURE_DIR, name)
        with open(path, "wb") as handle:
            handle.write(_make_pdf_bytes(lines))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
