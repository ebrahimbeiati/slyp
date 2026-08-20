"""
Scratch verification script — NOT part of the shipped test suite.

Tests slyp.extraction's redaction pipeline against PII format variations
the existing test suite (tests/test_extraction.py) does not cover, per
verification-prompt.md Phase 3, items 12-14.

Run: python verify/test_redaction_adversarial.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slyp.extraction import redact, financial_lines_only, assert_safe_to_send, RedactionFailure

CASES = [
    # (label, text, should_be_fully_redacted)
    ("NI no spaces", "NI Number AB123456C National Insurance 0.00", True),
    ("NI lowercase", "NI Number ry 44 99 43 d National Insurance 0.00", True),
    ("NI split across newline", "NI Number RY 44 99\n43 D National Insurance 0.00", True),
    ("NI with periods (adversarial)", "NI Number AB.12.34.56.C National Insurance 0.00", None),
    ("Sort code with slashes (adversarial)", "Sort Code 12/34/56 Account 12345678", None),
    ("Sort code with dashes", "Sort Code 12-34-56 Account 12345678", True),
    ("Sort code with spaces", "Sort Code 12 34 56 Account 12345678", True),
    ("Address multi-line postcode only", "123 Fake Street\nFaketown\nSW1A 1AA", True),
]

def run():
    failures = []
    for label, text, expect_full in CASES:
        redacted, rmap = redact(text)
        filtered = financial_lines_only(redacted)
        try:
            assert_safe_to_send(filtered)
            gate_raised = False
        except RedactionFailure as e:
            gate_raised = True

        # Did raw digits/letters of the PII survive into the redacted text?
        print(f"\n=== {label} ===")
        print(f"  original : {text!r}")
        print(f"  redacted : {redacted!r}")
        print(f"  filtered : {filtered!r}")
        print(f"  gate raised RedactionFailure: {gate_raised}")

        if expect_full is True and gate_raised:
            failures.append(f"{label}: expected clean redaction, but gate STILL had to fire (means redact() left PII behind and only the final gate caught it, or a false positive)")

    print("\n\n=== SUMMARY ===")
    if failures:
        for f in failures:
            print("FAIL:", f)
    else:
        print("No hard failures flagged (see per-case output above for adversarial cases marked 'None' expectation - inspect manually).")

if __name__ == "__main__":
    run()
