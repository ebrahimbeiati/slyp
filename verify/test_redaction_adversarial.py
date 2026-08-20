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
    #
    # The two rows marked "was adversarial" used to be full bypasses (F6):
    # neither redact() nor the gate caught them, because the gate re-ran
    # the exact same regex that had already missed them. Both are fixed
    # now - NI/sort-code separators are generalised to tolerate space,
    # hyphen, slash and line breaks (period too for NI; deliberately not
    # for sort code/account number, which collide with currency decimals -
    # see the comment on _SORT_CODE_RE in slyp/extraction.py) - and the
    # gate has a second, independent check that doesn't depend on
    # recognising a specific PII shape at all.
    ("NI no spaces", "NI Number AB123456C National Insurance 0.00", True),
    ("NI lowercase", "NI Number ry 44 99 43 d National Insurance 0.00", True),
    ("NI split across newline", "NI Number RY 44 99\n43 D National Insurance 0.00", True),
    ("NI with periods (was adversarial)", "NI Number AB.12.34.56.C National Insurance 0.00", True),
    ("Sort code with slashes (was adversarial)", "Sort Code 12/34/56 Account 12345678", True),
    ("Sort code with dashes", "Sort Code 12-34-56 Account 12345678", True),
    ("Sort code with spaces", "Sort Code 12 34 56 Account 12345678", True),
    ("Sort code with mixed separators", "Sort Code 12-34/56 Account 12345678", True),
    ("Address multi-line postcode only", "123 Fake Street\nFaketown\nSW1A 1AA", True),
    (
        # redact() has no pattern at all for an arbitrary internal
        # reference number - this is only "safe" because the gate's
        # second, independent layer refuses it. Different expectation
        # from the rows above: here the gate firing IS the pass condition.
        "Unknown PII shape, caught only by the gate's second layer",
        "Some Internal Reference 123456789 National Insurance 0.00",
        "gate",
    ),
]

def run():
    failures = []
    for label, text, expect in CASES:
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

        if expect is True and gate_raised:
            failures.append(f"{label}: expected clean redaction, but gate STILL had to fire (means redact() left PII behind and only the final gate caught it, or a false positive)")
        elif expect == "gate" and not gate_raised:
            failures.append(f"{label}: expected the gate to refuse this payload (redact() has no pattern for it), but nothing caught it - PII would have been sent")

    print("\n\n=== SUMMARY ===")
    if failures:
        for f in failures:
            print("FAIL:", f)
    else:
        print("Every case redacted cleanly or refused by the gate - never sent unprotected. (Rows with expectation 'gate' are meant to be caught by assert_safe_to_send's independent check, not by redact() - see slyp/extraction.py.)")

if __name__ == "__main__":
    run()
