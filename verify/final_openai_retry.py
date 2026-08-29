"""Item 29: on the reasoning_effort retry, do BOTH requests carry the same
already-redacted, already-gated payload? Forced, not observed by luck."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
import openai
from slyp import extraction as E

sent = []
gated = []

# record what the gate actually approved
_real_gate = E.assert_safe_to_send
def spy_gate(payload):
    gated.append(payload)
    return _real_gate(payload)
E.assert_safe_to_send = spy_gate

class _FakeResp:
    class _M:
        tool_calls = None
    choices = [type("C", (), {"message": _M()})()]

calls = {"n": 0}
class FakeCompletions:
    def create(self, **kw):
        calls["n"] += 1
        sent.append((kw.get("reasoning_effort", "<not sent>"),
                     kw["messages"][1]["content"]))
        if calls["n"] == 1:
            raise openai.BadRequestError(
                "Function tools with reasoning_effort are not supported for "
                "gpt-5.6-sol in /v1/chat/completions. To use function tools, "
                "use /v1/responses or set reasoning_effort to 'none'.",
                response=type("R", (), {"status_code": 400, "headers": {},
                                        "request": None})(), body=None)
        return _FakeResp()

class FakeClient:
    chat = type("Chat", (), {"completions": FakeCompletions()})()

E.openai.OpenAI = lambda *a, **k: FakeClient()
E._MODEL_PROVIDER = "openai"
E._OPENAI_NEEDS_REASONING_EFFORT_NONE = False

pdf = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "emergency_m1_midyear_start.pdf"), "rb").read()
try:
    E.extract_payslip(pdf, filename="f.pdf")
except E.NotAPayslip:
    pass  # fake response has no tool call - fine, we only care about the payloads

print(f"gate ran {len(gated)} time(s)")
print(f"model requests made: {len(sent)}")
for i, (eff, payload) in enumerate(sent, 1):
    print(f"\n  request {i}: reasoning_effort={eff!r}")
    print(f"    payload == the gate-approved payload: {payload == gated[0]}")
    print(f"    payload contains a raw NI number:     {'AB 12 34 56 C' in payload}")
    print(f"    payload first line: {payload.splitlines()[0]!r}")

print(f"\n  BOTH requests carried the identical gated payload: "
      f"{len(sent) == 2 and sent[0][1] == sent[1][1] == gated[0]}")
print(f"  a SECOND, ungated payload was built: "
      f"{len({p for _, p in sent}) > 1}  (must be False)")
print(f"\n  flag now sticky for the process: {E._OPENAI_NEEDS_REASONING_EFFORT_NONE}")
calls["n"] = 0; sent.clear()
try: E.extract_payslip(pdf, filename="f.pdf")
except E.NotAPayslip: pass
print(f"  second upload made {len(sent)} request(s) "
      f"(reasoning_effort={sent[0][0]!r}) - no repeat 400")
