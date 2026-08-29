"""Does the blocking model call inside `async def analyse` stall the event loop?"""
import sys, os, io, json, time, uuid, threading, urllib.request
BASE = "http://127.0.0.1:8011"
HERE = os.path.dirname(os.path.abspath(__file__))

def post(pdf):
    b = uuid.uuid4().hex; body = io.BytesIO()
    body.write(f"--{b}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="file"; filename="p.pdf"\r\n'
               b'Content-Type: application/pdf\r\n\r\n')
    body.write(pdf); body.write(f"\r\n--{b}--\r\n".encode())
    req = urllib.request.Request(f"{BASE}/analyse", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=180) as r: r.read()

with open(os.path.join(HERE,"fixtures","emergency_m1_midyear_start.pdf"),"rb") as f:
    pdf = f.read()

# baseline /health latency
t=time.monotonic(); urllib.request.urlopen(f"{BASE}/health", timeout=10).read()
print(f"baseline /health: {(time.monotonic()-t)*1000:.0f} ms")

done = threading.Event()
def upload():
    post(pdf); done.set()
th = threading.Thread(target=upload); th.start()
time.sleep(0.8)   # upload is now mid-model-call

samples=[]
while not done.is_set() and len(samples) < 12:
    t=time.monotonic()
    try:
        urllib.request.urlopen(f"{BASE}/health", timeout=30).read()
        samples.append((time.monotonic()-t)*1000)
    except Exception as e:
        samples.append(-1.0)
    time.sleep(0.25)
th.join()
print(f"/health during upload: {[f'{s:.0f}' for s in samples]} ms")
worst = max(samples) if samples else 0
print(f"worst /health latency while a model call is in flight: {worst:.0f} ms")
print("=> event loop is", "BLOCKED" if worst > 500 else "not blocked")
