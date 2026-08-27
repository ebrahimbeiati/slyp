"""
What each fixture renders on the results screen after the CLEAR-findings
split, using LIVE API responses.

Mirrors app/page.tsx exactly:
    SEVERITY_ORDER  = action 0, advisory 1, clear 2
    foundFindings     = sorted, severity !== "clear"   -> "What we found"
    confirmedFindings = sorted, severity === "clear"   -> "What we confirmed"
    each section renders only when its group is non-empty
"""
from __future__ import annotations
import io, json, os, sys, uuid, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8030"
HERE = os.path.dirname(os.path.abspath(__file__))

SEVERITY_ORDER = {"action": 0, "advisory": 1, "clear": 2}


def post(name, only_job):
    with open(os.path.join(HERE, "fixtures", name), "rb") as fh:
        pdf = fh.read()
    b = uuid.uuid4().hex
    body = io.BytesIO()

    def part(header, data):
        body.write(f"--{b}\r\n{header}\r\n\r\n".encode())
        body.write(data)
        body.write(b"\r\n")

    part('Content-Disposition: form-data; name="file"; filename="p.pdf"\r\n'
         "Content-Type: application/pdf", pdf)
    if only_job is not None:
        part('Content-Disposition: form-data; name="only_job"',
             str(only_job).lower().encode())
    body.write(f"--{b}--\r\n".encode())
    req = urllib.request.Request(
        f"{BASE}/analyse", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


CASES = [
    ("BR £476, only_job=false", "br_second_job.pdf", False),
    ("BR £476, only_job=true", "br_second_job.pdf", True),
    ("emergency M1 mid-year start", "emergency_m1_midyear_start.pdf", True),
    ("£583.55 under threshold", "under_all_thresholds.pdf", True),
]

results = {}
for label, fixture, only_job in CASES:
    payload = post(fixture, only_job)
    results[label] = payload

    findings = sorted(payload.get("findings", []),
                      key=lambda f: SEVERITY_ORDER[f["severity"]])
    found = [f for f in findings if f["severity"] != "clear"]
    confirmed = [f for f in findings if f["severity"] == "clear"]

    print("=" * 78)
    print(label)
    print("=" * 78)
    print(f'  VERDICT   "{payload["verdict"]["headline"]}"')
    if found:
        print("  ── What we found ──")
        for f in found:
            est = f.get("estimate")
            money = f'  [{est["label"]}: £{est["amount_gbp"]}]' if est else ""
            print(f'      [{f["severity"]}] {f["title"]}{money}')
    else:
        print("  (no 'What we found' section)")
    if confirmed:
        print("  ── What we confirmed ──")
        for f in confirmed:
            print(f'      [{f["severity"]}] {f["title"]}')
    else:
        print("  (no 'What we confirmed' section)")
    score = payload.get("score") or {}
    print(f'  WHAT WE CHECKED  {score.get("checks_passed")} of '
          f'{score.get("checks_run")} passed, '
          f'{len(score.get("not_applicable") or [])} not applicable')
    print()

with open(os.path.join(HERE, "_render_results.json"), "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=1)
print("saved verify/_render_results.json for the payroll-message check")
