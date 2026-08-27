"""Item 36: error paths return clean, non-technical messages over HTTP.
Also items 35, 38, 39. Runs against a live server."""
import sys, os, io, json, time, urllib.request, urllib.error, uuid

BASE = os.environ.get("SLYP_TEST_BASE", "http://127.0.0.1:8011")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def post(pdf_bytes, filename="t.pdf", only_job=None, field="file"):
    b = uuid.uuid4().hex
    body = io.BytesIO()
    def part(hdr, data):
        body.write(f"--{b}\r\n{hdr}\r\n\r\n".encode()); body.write(data); body.write(b"\r\n")
    if pdf_bytes is not None:
        part(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
             f"Content-Type: application/pdf", pdf_bytes)
    if only_job is not None:
        part('Content-Disposition: form-data; name="only_job"', str(only_job).encode())
    body.write(f"--{b}--\r\n".encode())
    data = body.getvalue()
    req = urllib.request.Request(f"{BASE}/analyse", data=data, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read()), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: payload = json.loads(raw)
        except Exception: payload = {"raw": raw[:300].decode("utf-8", "replace")}
        return e.code, payload, time.monotonic() - t0

def msg(p):
    return p.get("detail") or p.get("failure_reason") or json.dumps(p)[:160]

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
def fixture(name):
    with open(os.path.join(FIX, name), "rb") as f: return f.read()

def looks_technical(text):
    bad = ["Traceback", "Error:", "Exception", "line ", "File \"", "pdfminer",
           "pdfplumber", "slyp/", "None", "null", "0x", "__"]
    return [w for w in bad if w in text]

print("=" * 78)
print("ITEM 36 - error paths")
print("=" * 78)

cases = []

# corrupt PDF: valid magic bytes, garbage body
cases.append(("corrupt PDF", b"%PDF-1.4\n" + os.urandom(400), None))
# empty file
cases.append(("empty file", b"", None))
# not a PDF at all (magic byte check)
cases.append(("not a PDF (magic bytes)", b"GIF89a" + os.urandom(200), None))
# oversized
cases.append(("oversized file (>10MB)", b"%PDF-1.4\n" + b"A" * (11 * 1024 * 1024), None))
# image-only PDF: valid PDF, no text layer
imageonly = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
             b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
             b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>\nendobj\n"
             b"trailer\n<< /Size 4 /Root 1 0 R >>\n%%EOF\n")
cases.append(("image-only / no text layer", imageonly, None))

for label, data, oj in cases:
    status, payload, secs = post(data, only_job=oj)
    m = msg(payload)
    tech = looks_technical(m)
    print(f"\n{label}")
    print(f"  HTTP {status}   {secs:.2f}s")
    print(f"  message: {m}")
    print(f"  technical leakage: {tech or 'none'}")
