"""
Diagnose a gate refusal on a real payslip.

    python verify/final_worktable_gate.py path\\to\\payslip.pdf
    python verify/final_worktable_gate.py                 (synthetic control)

OUTPUT IS SAFE TO PASTE. Everything printed to stdout is shape-masked:
digits become #, letters become A or a, punctuation and spacing are kept.
That is enough to identify which pattern matched what shape, and carries
no name, no NI number, no account number and no figure. The whole point of
this codebase is that payslip content does not leave the machine, and that
applies to a debugging session too.

If you want the real strings for your own eyes, add --unmasked. That
writes to verify/_gate_diagnosis.txt on this machine and still prints only
the masked version. Do not send that file anywhere.

Pure pathlib/re - no subprocess, nothing shelled out, so it behaves the
same in PowerShell, cmd and a POSIX shell.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from slyp import extraction as E  # noqa: E402


# ==========================================================================
# Masking
# ==========================================================================

def mask(text: str) -> str:
    """Digits -> #, letters -> A/a, everything else kept.

    Preserves length, case pattern, punctuation and spacing, which is what
    identifies a shape: '####/###/##' is a job reference and '##/##/####'
    is a date, and neither tells you anything about the person.
    """
    out = []
    for ch in text:
        if ch.isdigit():
            out.append("#")
        elif ch.isalpha():
            out.append("A" if ch.isupper() else "a")
        else:
            out.append(ch)
    return "".join(out)


UNMASKED = "--unmasked" in sys.argv
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
_unmasked_log: list[str] = []


def emit(label: str, raw: str) -> None:
    """Print the masked form; keep the raw one for the local file only."""
    print(f"{label}{mask(raw)}")
    if UNMASKED:
        _unmasked_log.append(f"{label}{raw}")


def show(title: str) -> None:
    print("\n" + "=" * 76)
    print(title)
    print("=" * 76)


# ==========================================================================
# Input
# ==========================================================================

SYNTHETIC = "\n".join([
    "Employer: Fizz Wholesale Data Services Ltd",
    "Employee Name: Mr K SAMPLE",
    "Works Number: 4471",
    "Pay Date: 31/07/2026",
    "NI No:            NI Rate:M   Tax Code: 1257L   Month No:5",
    "Payments                        Deductions",
    "Basic Pay 1,842.00              Income Tax 214.90",
    "                                National Insurance 95.52",
    "Total Gross Pay 1,842.00        Net Pay 1,531.58",
    "Work Record",
    "Demo Number   Date        Description        Hours   Rate      Total",
    "4471021       20/07/2026  ES601UK Install     2.50   15.3846   38.46",
    "4471/021/26   21/07/2026  ES601UK Repair      1.75   15.3846   26.92",
])

if ARGS:
    pdf_path = Path(ARGS[0]).expanduser()
    if not pdf_path.is_file():
        print(f"No such file: {pdf_path}")
        raise SystemExit(2)
    try:
        text, pages = E._read_pdf(pdf_path.read_bytes())
    except Exception as exc:
        print(f"Could not read {pdf_path.name}: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    source = f"{pdf_path.name} ({pages} page(s), {len(text)} chars of text)"
else:
    text, source = SYNTHETIC, "SYNTHETIC control (no file given)"

print("=" * 76)
print("GATE DIAGNOSIS")
print("=" * 76)
print(f"  source : {source}")
print(f"  output : shape-masked{' (raw copy -> verify/_gate_diagnosis.txt)' if UNMASKED else ''}")


# ==========================================================================
# 1-3. Pipeline
# ==========================================================================

show("1. EXTRACTED TEXT (masked)")
for i, line in enumerate(text.splitlines(), 1):
    if line.strip():
        emit(f"  {i:>3} | ", line)

redacted, _ = E.redact(text)
show("2. AFTER redact() (masked)")
for i, line in enumerate(redacted.splitlines(), 1):
    if line.strip():
        emit(f"  {i:>3} | ", line)

filtered = E.financial_lines_only(redacted)
show("3. AFTER financial_lines_only() - what the gate sees (masked)")
for i, line in enumerate(filtered.splitlines(), 1):
    if line.strip():
        emit(f"  {i:>3} | ", line)


# ==========================================================================
# 4. The gate, instrumented
# ==========================================================================

show("4. GATE - which pattern matched which shape")

refused = None
try:
    E.assert_safe_to_send(filtered)
    print("  gate PASSED")
except E.RedactionFailure as exc:
    refused = str(exc)
    print(f"  gate REFUSED: {exc}")

print("\n  check 1 - PII re-scan:")
for label, pattern, skip_if in E._PII_RECHECK_PATTERNS:
    hits = []
    for m in pattern.finditer(filtered):
        if skip_if is not None and skip_if(m.group(0)):
            continue
        hits.append(m.group(0))
    if not hits:
        print(f"    {label:16} -")
        continue
    print(f"    {label:16} {len(hits)} match(es)")
    print(f"    {'':16} pattern: {pattern.pattern}")
    for h in hits[:5]:
        emit(f"    {'':16} shape  : ", h)
        line = next((l for l in filtered.splitlines() if h in l), "")
        emit(f"    {'':16} on line: ", line.strip())

masked_payload = E._mask_known_safe_numbers(filtered)
print("\n  check 2 - after masking every explained numeric shape:")
for name, pattern in (("unexplained digit run", E._UNEXPLAINED_DIGIT_RUN_RE),
                      ("split digit groups", E._SPLIT_DIGIT_GROUPS_RE)):
    hits = [m.group(0) for m in pattern.finditer(masked_payload)]
    if not hits:
        print(f"    {name:22} -")
        continue
    print(f"    {name:22} {len(hits)} match(es)")
    print(f"    {'':22} pattern: {pattern.pattern}")
    for h in hits[:5]:
        emit(f"    {'':22} shape  : ", h)
        line = next((l for l in filtered.splitlines()
                     if re.sub(r"\s+", "", h) in re.sub(r"\s+", "", l)), "")
        if line:
            emit(f"    {'':22} on line: ", line.strip())


# ==========================================================================
# 5. Candidate shapes, tested against this document
# ==========================================================================

show("5. CANDIDATE SHAPES FOUND IN THIS DOCUMENT")

CANDIDATES = [
    ("punctuated reference  ####/###/##", re.compile(r"(?<![\d.])\b\d{2,4}(?:[/-]\d{2,4}){2,}\b")),
    ("date DD/MM/YYYY",                   re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")),
    ("date DD/MM/YY (collides w/ sort)",  re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{2}\b(?!\d)")),
    ("decimal with 7+ places",            re.compile(r"\b\d[\d,]*\.\d{7,}\b")),
    ("alphanumeric product code",         re.compile(r"\b[A-Z]{2,}\d{2,}[A-Z]{0,3}\b")),
    ("label with empty value (NI No:)",   re.compile(r"(?i)\bNI\s*No\.?\s*:\s*(?=\s|$)")),
    ("NI Rate:<letter>",                  re.compile(r"(?i)\bNI\s*Rate\s*:\s*[A-Z]\b")),
    ("Month No:<n>",                      re.compile(r"(?i)\bMonth\s*No\.?\s*:\s*\d{1,2}\b")),
    ("6+ digits contiguous",              re.compile(r"(?<![\d.])\b\d{6,}\b(?!\.\d)")),
]
for label, pattern in CANDIDATES:
    hits = [m.group(0) for m in pattern.finditer(text)]
    if hits:
        shapes = sorted({mask(h) for h in hits})
        print(f"  {label:36} {len(hits):>3}x  {', '.join(shapes[:4])}")
    else:
        print(f"  {label:36}   -")


# ==========================================================================
# 6. Date-survival test coverage (pure Python, no subprocess)
# ==========================================================================

show("6. DATE-SURVIVAL TEST COVERAGE")

test_file = ROOT / "tests" / "test_extraction.py"
src = test_file.read_text(encoding="utf-8")

names = re.findall(r"^def (test_\w*date\w*)", src, re.M)
print(f"  date-named tests in {test_file.name}: {len(names)}")
for n in names:
    print(f"    {n}")

print("\n  date formats used as parametrised fixtures:")
for m in re.finditer(r'"(\d{1,4}[/-]\d{1,2}[/-]\d{1,4})"', src):
    print(f"    {m.group(1)}")

# Named carefully: a test can mention both "date" and "sort code" while
# asserting the OPPOSITE of date survival - test_sort_code_with_slashes_
# bypass_not_reopened_by_the_date_exemption asserts a sort code IS
# redacted. So report the two separately rather than letting a keyword
# co-occurrence read as coverage.
print("\n  tests naming a date that also mention the sort-code pattern:")
blocks = re.split(r"\ndef (test_\w+)", src)
for i in range(1, len(blocks), 2):
    name, body = blocks[i], blocks[i + 1]
    if re.search(r"date", name, re.I) and re.search(r"sort.?code|_SORT_CODE_RE", body, re.I):
        asserts_survival = bool(re.search(r"assert\s+\w*date\w*\s+in\s", body, re.I))
        verdict = ("asserts a date SURVIVES it" if asserts_survival
                   else "asserts a sort code is REDACTED - not date-survival coverage")
        print(f"    {name}")
        print(f"      -> {verdict}")


if UNMASKED:
    out = ROOT / "verify" / "_gate_diagnosis.txt"
    out.write_text("\n".join(_unmasked_log), encoding="utf-8")
    print(f"\n  raw detail written to {out} - local only, do not share it")
