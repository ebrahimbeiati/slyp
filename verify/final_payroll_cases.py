"""Capture the five cases the payroll message must read well for."""
import io, json, os, sys, uuid, urllib.request
from decimal import Decimal as D
from datetime import date, datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE, HERE = "http://127.0.0.1:8050", os.path.dirname(os.path.abspath(__file__))

def post(name, only_job):
    with open(os.path.join(HERE, "fixtures", name), "rb") as fh: pdf = fh.read()
    b = uuid.uuid4().hex; body = io.BytesIO()
    def part(h, d):
        body.write(f"--{b}\r\n{h}\r\n\r\n".encode()); body.write(d); body.write(b"\r\n")
    part('Content-Disposition: form-data; name="file"; filename="p.pdf"\r\n'
         "Content-Type: application/pdf", pdf)
    if only_job is not None:
        part('Content-Disposition: form-data; name="only_job"', str(only_job).lower().encode())
    body.write(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{BASE}/analyse", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=180) as r: return json.loads(r.read())

out = {
    "BR second job (only_job=false)":  post("br_second_job.pdf", False),
    "BR only job (only_job=true)":     post("br_second_job.pdf", True),
    "Emergency M1 mid-year start":     post("emergency_m1_midyear_start.pdf", True),
    "Emergency M1, not told":          post("emergency_m1_midyear_start.pdf", None),
    "Under all thresholds":            post("under_all_thresholds.pdf", True),
}

# The dirty payslip from the brief, built locally: tax GBP 41.00 over and a
# reconciliation gap of the same GBP 41.00.
from slyp.contract import (PayslipExtract, Period, TaxCodeRead, Pay, Deductions,
                           Source, UserContext)
from slyp.analysis import analyse_payslip
dirty = analyse_payslip(PayslipExtract(
    source=Source(filename="p.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
    period=Period(pay_date=date(2026,4,30), period_number=1, frequency="monthly",
                  tax_year="2026/27"),
    tax_code=TaxCodeRead(value="1257L"),
    pay=Pay(gross_this_period=D("1240.00"), gross_ytd=D("1240.00")),
    deductions=Deductions(income_tax=D("79.50"), national_insurance=D("15.36"),
                          pension_employee=D("62.00")),
    net_pay=D("1124.14"), reconciles=False,
), UserContext(only_job=True))
out["Dirty payslip (tax + reconciliation, both GBP 41.00)"] = json.loads(dirty.model_dump_json())

with open(os.path.join(HERE, "_payroll_cases.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("captured", len(out), "cases")
