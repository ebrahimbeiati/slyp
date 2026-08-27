"""Items 35, 36 (remaining), 38, 39, 8 - against a live server."""
import sys, os, io, json, time, uuid, urllib.request, urllib.error, re
BASE = os.environ.get("SLYP_TEST_BASE", "http://127.0.0.1:8011")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

def _pdf(lines):
    ops = ["BT", "/F1 10 Tf", "20 800 Td"]
    for line in lines:
        esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops += [f"({esc}) Tj", "0 -13 Td"]
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n"); offs = []
    for i, body in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for o in offs: out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)

def post(pdf_bytes, filename="t.pdf", only_job=None):
    b = uuid.uuid4().hex; body = io.BytesIO()
    def part(hdr, data):
        body.write(f"--{b}\r\n{hdr}\r\n\r\n".encode()); body.write(data); body.write(b"\r\n")
    if pdf_bytes is not None:
        part(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             'Content-Type: application/pdf', pdf_bytes)
    if only_job is not None:
        part('Content-Disposition: form-data; name="only_job"', str(only_job).encode())
    body.write(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{BASE}/analyse", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read()), time.monotonic()-t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: p = json.loads(raw)
        except Exception: p = {"raw": raw[:200].decode("utf-8","replace")}
        return e.code, p, time.monotonic()-t0

def show(label, status, payload, secs):
    detail = payload.get("detail")
    print(f"\n{label}\n  HTTP {status}  {secs:.2f}s")
    if detail:
        print(f"  message: {detail}")
    else:
        print(f"  status={payload.get('status')!r}  reason={payload.get('failure_reason')!r}")
        v = payload.get("verdict") or {}
        print(f"  verdict: {v.get('headline')!r}")
    tech = [w for w in ["Traceback","pdfminer","pdfplumber","slyp.","File \"","line ","0x"]
            if w in json.dumps(payload)]
    print(f"  technical leakage in body: {tech or 'none'}")

def fixture(n):
    with open(os.path.join(HERE, "fixtures", n), "rb") as f: return f.read()

print("="*78); print("ITEM 36 (cont.) - remaining error paths"); print("="*78)

# password-protected: minimal PDF with an /Encrypt trailer entry
enc = _pdf(["Gross 2,500.00"]).replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 6 0 R")
show("password-protected PDF", *post(enc, "locked.pdf"))

# gate refusal
show("gate refusal (unexplained digit groups)", *post(_pdf([
    "Pay Date: 28/08/2026", "Tax Code: 1257L    NI Table Letter A",
    "Code 123 456 789   Basic Pay 2,500.00",
    "Total Gross Pay 2,500.00   Net Pay 2,000.00",
    "Gross Pay YTD 7,500.00   Income Tax YTD 871.50"]), "gate.pdf"))

# unsupported tax year (pay date in 2025/26)
show("unsupported tax year (pay date 28/08/2025)", *post(_pdf([
    "Employer: Northwind Trading Ltd", "Pay Date: 28/08/2025",
    "Tax Period: 5    Payment Period Monthly",
    "Tax Code: 1257L    NI Table Letter A",
    "Basic Pay 2,500.00    Income Tax 290.50",
    "                      National Insurance 116.16",
    "Total Gross Pay 2,500.00   Net Pay 2,093.34",
    "Gross Pay YTD 12,500.00    Income Tax YTD 1,452.50"]), "oldyear.pdf"))

print("\n" + "="*78); print("ITEM 35 - reconciliation flags rather than proceeds"); print("="*78)
# gross - deductions != net, deliberately
st, p, s = post(_pdf([
    "Employer: Northwind Trading Ltd", "Pay Date: 28/08/2026",
    "Tax Period: 5    Payment Period Monthly",
    "Tax Code: 1257L    NI Table Letter A",
    "Basic Pay 2,500.00    Income Tax 290.50",
    "                      National Insurance 116.16",
    "Total Gross Pay 2,500.00   Net Pay 1,500.00",
    "Gross Pay YTD 12,500.00    Income Tax YTD 1,452.50",
    "                           National Insurance YTD 580.80"]), "badrecon.pdf", only_job=True)
print(f"  HTTP {st}  {s:.2f}s  status={p.get('status')!r}")
print(f"  reconciles = {(p.get('extract') or {}).get('reconciles')!r}")
for f in p.get("findings", []):
    print(f"    {f['severity']:8} {f['id']}")
sc = p.get("score") or {}
print(f"  score: value={sc.get('value')} {sc.get('checks_passed')}/{sc.get('checks_run')}")
print(f"  verdict: {(p.get('verdict') or {}).get('headline')!r}")

print("\n" + "="*78); print("ITEM 38 + 8 - end-to-end latency and determinism (5 runs)"); print("="*78)
demo = fixture("emergency_m1_midyear_start.pdf")
sigs, times = [], []
for i in range(5):
    st, p, s = post(demo, "emergency_m1_midyear_start.pdf", only_job=True)
    times.append(s)
    money = sorted(re.findall(r"£[\d,]+\.\d{2}", json.dumps(p)))
    est = next((f["estimate"]["amount_gbp"] for f in p.get("findings", [])
                if f.get("estimate")), None)
    sc = p.get("score") or {}
    sig = json.dumps({"status": p.get("status"), "est": est,
                      "score": sc.get("value"), "checks": [sc.get("checks_passed"), sc.get("checks_run")],
                      "findings": sorted(f["id"] for f in p.get("findings", [])),
                      "money": money}, sort_keys=True)
    sigs.append(sig)
    print(f"  run {i+1}: {s:5.2f}s  estimate={est}  score={sc.get('value')} "
          f"({sc.get('checks_passed')}/{sc.get('checks_run')})")
print(f"\n  latency: min {min(times):.2f}s  max {max(times):.2f}s  mean {sum(times)/len(times):.2f}s")
print(f"  byte-identical across 5 runs: {len(set(sigs)) == 1}")
if len(set(sigs)) != 1:
    for i, s_ in enumerate(sigs, 1): print(f"    run {i}: {s_}")
