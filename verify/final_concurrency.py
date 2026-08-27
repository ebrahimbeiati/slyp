"""Item 39: double-click submit / two rapid uploads."""
import sys, os, io, json, time, uuid, threading, urllib.request, urllib.error
BASE = os.environ.get("SLYP_TEST_BASE", "http://127.0.0.1:8011")
HERE = os.path.dirname(os.path.abspath(__file__))

def post(pdf, only_job=None):
    b = uuid.uuid4().hex; body = io.BytesIO()
    def part(h, d):
        body.write(f"--{b}\r\n{h}\r\n\r\n".encode()); body.write(d); body.write(b"\r\n")
    part('Content-Disposition: form-data; name="file"; filename="p.pdf"\r\n'
         'Content-Type: application/pdf', pdf)
    if only_job is not None:
        part('Content-Disposition: form-data; name="only_job"', str(only_job).encode())
    body.write(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{BASE}/analyse", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.loads(r.read()), time.monotonic()-t0

def fx(n):
    with open(os.path.join(HERE, "fixtures", n), "rb") as f: return f.read()

a = fx("emergency_m1_midyear_start.pdf")   # expects £419.00
c = fx("br_second_job.pdf")                # expects the BR finding, no estimate

results = {}
def run(key, pdf, oj):
    try: results[key] = post(pdf, oj)
    except Exception as e: results[key] = ("ERR", {"e": repr(e)}, 0)

print("=== A: same file submitted twice simultaneously (double-click) ===")
ts = [threading.Thread(target=run, args=(f"dbl{i}", a, True)) for i in (1, 2)]
[t.start() for t in ts]; [t.join() for t in ts]
for k in ("dbl1", "dbl2"):
    st, p, s = results[k]
    est = next((f["estimate"]["amount_gbp"] for f in p.get("findings", []) if f.get("estimate")), None)
    print(f"  {k}: HTTP {st}  {s:.2f}s  estimate={est}  findings={sorted(f['id'] for f in p.get('findings',[]))}")
same = results["dbl1"][1] == results["dbl2"][1]
print(f"  identical bodies: {same}  (expected True - same input, deterministic)")

print("\n=== B: two DIFFERENT files submitted simultaneously (interleaving) ===")
results.clear()
ts = [threading.Thread(target=run, args=("emg", a, True)),
      threading.Thread(target=run, args=("br", c, False))]
[t.start() for t in ts]; [t.join() for t in ts]
for k, expect in (("emg", "419.00"), ("br", "no estimate")):
    st, p, s = results[k]
    est = next((f["estimate"]["amount_gbp"] for f in p.get("findings", []) if f.get("estimate")), None)
    ids = sorted(f["id"] for f in p.get("findings", []))
    sc = p.get("score") or {}
    print(f"  {k}: HTTP {st} {s:.2f}s estimate={est} score={sc.get('checks_passed')}/{sc.get('checks_run')}")
    print(f"       findings={ids}  (expected: {expect})")
emg_ok = next((f["estimate"]["amount_gbp"] for f in results["emg"][1]["findings"] if f.get("estimate")), None) == "419.00"
br_ok  = all(not f.get("estimate") for f in results["br"][1]["findings"]) and \
         "tax_code_br_multiple_jobs" in {f["id"] for f in results["br"][1]["findings"]}
print(f"\n  no cross-contamination: emergency correct={emg_ok}  BR correct={br_ok}")
