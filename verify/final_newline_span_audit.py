"""
Audit every regex in slyp/extraction.py for matches that can span a line
break.

`\\s` matches `\\n`. A PII pattern that uses it as an internal separator can
therefore match the tail of one line and the head of the next, and when
redact() substitutes a token for that match it deletes the newline too -
welding two rows into one. That is not a hypothetical: it is how
_SORT_CODE_RE turned three work-record rows into a single line, matching
'46\\n20/07' (a total's pence, a newline, and the next row's DD/MM).

Reports. Changes nothing.
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


# Each probe is a two-line string built so the pattern's whitespace class
# lands exactly on the line break. If the pattern matches across it, the
# match will contain a newline.
PROBES: list[tuple[str, re.Pattern, str, str]] = [
    ("_NI_NUMBER_RE", E._NI_NUMBER_RE,
     "NI Number AB 12 34\n56 C", "separator class _SEP = [\\s./-]*"),
    ("_POSTCODE_RE", E._POSTCODE_RE,
     "Address LS7\n4QT", "\\s* between outward and inward code"),
    ("_SORT_CODE_RE", E._SORT_CODE_RE,
     "Total 38.46\n20/07/2026 Repair", "[-\\s/] separator  <-- THE REPORTED BUG"),
    ("_ACCOUNT_NUMBER_RE", E._ACCOUNT_NUMBER_RE,
     "Total 12.34\n5678 Repair", "[-\\s/]? between every digit"),
    ("_PHONE_RE", E._PHONE_RE,
     "Tel 0113\n4960112", "\\s? after +44 and [\\s-]? between digits"),
    ("_EMPLOYEE_NO_LABEL_RE", E._EMPLOYEE_NO_LABEL_RE,
     "Works Number\n4471021", "\\s*:?\\s* between label and value"),
    ("_NAME_LABEL_RE", E._NAME_LABEL_RE,
     "Name\nBasic Pay 1,842.00", "\\s*:?\\s* before the captured value"),
    ("_ADDRESS_LABEL_RE", E._ADDRESS_LABEL_RE,
     "Address\nBasic Pay 1,842.00", "\\s*:?\\s* before the captured value"),
    ("_EMPLOYER_LABEL_RE", E._EMPLOYER_LABEL_RE,
     "Employer\n: Northwind Ltd", "\\s*:\\s* between label and value"),
    ("_TITLED_NAME_RE", E._TITLED_NAME_RE,
     "Mr\nSAMPLE Basic Pay", "\\s+ before each following name token"),
    ("_DATE_RE", E._DATE_RE,
     "Period 15\nJan 2026", "[-\\s] before a month name"),
    ("_PERCENT_RE", E._PERCENT_RE,
     "Rate 5\n%", "\\s? before the percent sign"),
    ("_MONTHLY_LABEL_RE", E._MONTHLY_LABEL_RE,
     "Tax\nMonth 9", "\\s+ / \\s* around the label"),
    ("_WEEKLY_LABEL_RE", E._WEEKLY_LABEL_RE,
     "Tax\nWeek 39", "\\s+ / \\s* around the label"),
    ("_PAY_DATE_LABEL_RE", E._PAY_DATE_LABEL_RE,
     "Pay Date\n28/08/2026", "\\s* between label and value"),
    ("_UNSUPPORTED_FREQUENCY_RE", E._UNSUPPORTED_FREQUENCY_RE,
     "Pay\nFortnightly", "\\s* in the label"),
    # Controls: these use a literal space or no whitespace at all.
    ("_SPLIT_DIGIT_GROUPS_RE", E._SPLIT_DIGIT_GROUPS_RE,
     "12 34\n56", "literal space only - control"),
    ("_UNEXPLAINED_DIGIT_RUN_RE", E._UNEXPLAINED_DIGIT_RUN_RE,
     "123\n456", "[./-] only, no whitespace - control"),
    ("_UNEXPLAINED_ID_RE", E._UNEXPLAINED_ID_RE,
     "123\n456789", "no whitespace - control"),
    ("_CURRENCY_RE", E._CURRENCY_RE,
     "38\n.46", "no whitespace - control"),
    ("_EMAIL_RE", E._EMAIL_RE,
     "a@b\n.co.uk", "no whitespace - control"),
]

# Which patterns REPLACE text during redact() - a cross-line match there
# deletes the newline and merges two lines. The rest only decide whether a
# line is kept, or mask a span inside the gate.
SUBSTITUTES = {
    "_NI_NUMBER_RE", "_POSTCODE_RE", "_SORT_CODE_RE", "_ACCOUNT_NUMBER_RE",
    "_PHONE_RE", "_EMPLOYEE_NO_LABEL_RE", "_NAME_LABEL_RE",
    "_ADDRESS_LABEL_RE", "_TITLED_NAME_RE", "_UNEXPLAINED_ID_RE", "_EMAIL_RE",
}

print("=" * 96)
print("NEWLINE-SPANNING AUDIT - slyp/extraction.py")
print("=" * 96)
print(f"{'PATTERN':28} {'\\s?':4} {'SPANS':6} {'ROLE':10} EFFECT")
print("-" * 96)

spanning: list[tuple[str, str, str]] = []
for name, pattern, probe, note in PROBES:
    has_ws = bool(re.search(r"\\s", pattern.pattern))
    match = pattern.search(probe)
    spans = bool(match and "\n" in match.group(0))
    role = "redacts" if name in SUBSTITUTES else "matches"
    if spans:
        effect = "MERGES TWO LINES" if role == "redacts" else "match crosses rows"
        spanning.append((name, match.group(0), note))
    else:
        effect = "-"
    print(f"{name:28} {'yes' if has_ws else 'no':4} "
          f"{'YES' if spans else 'no':6} {role:10} {effect}")

print("-" * 96)
print(f"{len(spanning)} of {len(PROBES)} patterns can match across a line break\n")

if spanning:
    print("DETAIL")
    print("-" * 96)
    for name, matched, note in spanning:
        role = "REDACTS - a match here deletes the newline and merges the rows" \
            if name in SUBSTITUTES else \
            "matches only - no substitution, so no merge, but the match is wrong"
        print(f"  {name}")
        print(f"    matched : {matched!r}")
        print(f"    why     : {note}")
        print(f"    role    : {role}")
        print()
