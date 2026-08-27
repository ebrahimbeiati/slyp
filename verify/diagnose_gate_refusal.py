"""
Scratch diagnostic — NOT part of the shipped test suite, and NOT part of
the request path.

When /analyse returns 422 "refused by the redaction gate", this says
WHICH span tripped it. Everything runs locally: nothing is sent to any
API, and the payslip is never written anywhere.

Run: python verify/diagnose_gate_refusal.py path/to/payslip.pdf

The output prints spans from your own payslip, so treat it like the
payslip itself - read it in the terminal, don't paste it somewhere
public.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slyp.extraction import (  # noqa: E402
    _PII_RECHECK_PATTERNS,
    _SPLIT_DIGIT_GROUPS_RE,
    _UNEXPLAINED_DIGIT_RUN_RE,
    _has_unexempted_match,
    _mask_known_safe_numbers,
    _read_pdf,
    financial_lines_only,
    redact,
)


def main(path: str) -> int:
    with open(path, "rb") as handle:
        pdf_bytes = handle.read()

    text, pages = _read_pdf(pdf_bytes)
    redacted, _ = redact(text)
    payload = financial_lines_only(redacted)

    print(f"pages: {pages}")
    print(f"payload lines reaching the gate: {len(payload.splitlines())}\n")

    tripped = False

    for label, pattern, skip_if in _PII_RECHECK_PATTERNS:
        if _has_unexempted_match(pattern, payload, skip_if):
            tripped = True
            print(f"CHECK 1 tripped: {label}")
            for match in pattern.finditer(payload):
                if skip_if is not None and skip_if(match.group(0)):
                    continue
                print(f"    matched span: {match.group(0)!r}")
                print(f"    on line     : {_line_containing(payload, match.start())!r}")

    masked = _mask_known_safe_numbers(payload)

    for name, pattern in (
        ("unexplained run of digits", _UNEXPLAINED_DIGIT_RUN_RE),
        ("unexplained sequence of digit groups", _SPLIT_DIGIT_GROUPS_RE),
    ):
        for match in pattern.finditer(masked):
            tripped = True
            print(f"CHECK 2 tripped: {name}")
            print(f"    matched span   : {match.group(0)!r}")
            print(f"    masked line    : {_line_containing(masked, match.start())!r}")
            print(f"    original line  : {_line_containing(payload, match.start())!r}")

    if not tripped:
        print("Nothing trips the gate - this payload would be sent.")
        return 0

    print(
        "\nEach span above is what the gate could not explain. If a span is "
        "genuine PII, the gate did its job. If it's a legitimate payslip "
        "value, that's a masking gap - report the span (not the whole "
        "payslip)."
    )
    return 1


def _line_containing(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:] if end == -1 else text[start:end]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
