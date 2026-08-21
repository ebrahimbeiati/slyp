"""
The demo regression suite. Runs every fixture through the REAL pipeline -
extract_payslip() (a live model call) then analyse_payslip() - and asserts
the outcome each one exists to pin.

This is the end-to-end check. tests/test_fixture_outcomes.py pins the same
four outcomes at the analysis layer with no API call, so the fast loop
catches a logic regression instantly; this one catches the things only a
real extraction can break - a redaction change that eats a needed line, an
allowlist gap, a model that stops reading a label.

Run:  python verify/run_regression.py
      python verify/run_regression.py --runs 3     (stability)

Exits non-zero if any expectation fails, so it can gate a commit.
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from slyp.analysis import analyse_payslip  # noqa: E402
from slyp.contract import UserContext  # noqa: E402
from slyp.extraction import extract_payslip  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _estimate(result):
    return next((f.estimate for f in result.findings if f.estimate is not None), None)


def _finding_ids(result):
    return {f.id for f in result.findings}


# (label, fixture, only_job, expectation) - each expectation returns a list
# of failure strings, empty when the fixture behaved.
CASES = []


def case(label, fixture, only_job):
    def register(check):
        CASES.append((label, fixture, only_job, check))
        return check

    return register


@case("BR, second job", "br_second_job.pdf", False)
def _check_br(result):
    problems = []
    score = result.score
    if "tax_code_br_multiple_jobs" not in _finding_ids(result):
        problems.append(f"expected the BR second-job finding, got {_finding_ids(result)}")
    if _estimate(result) is not None:
        problems.append("a second job must never carry an overpayment estimate")
    if (score.checks_passed, score.checks_run) != (3, 3):
        problems.append(f"expected 3 of 3 checks, got {score.checks_passed} of {score.checks_run}")
    if not any("National Insurance" in reason for reason in score.not_applicable):
        problems.append(f"expected the NI not-applicable reason, got {score.not_applicable}")
    return problems


@case("Under all thresholds", "under_all_thresholds.pdf", True)
def _check_under(result):
    problems = []
    score = result.score
    if (score.checks_passed, score.checks_run) != (2, 2):
        problems.append(f"expected 2 of 2 checks, got {score.checks_passed} of {score.checks_run}")
    if len(score.not_applicable) != 2:
        problems.append(f"expected 2 not-applicable reasons, got {score.not_applicable}")
    return problems


@case("Emergency M1, only job (STATED)", "emergency_m1_midyear_start.pdf", True)
def _check_emergency_stated(result):
    problems = []
    estimate = _estimate(result)
    if estimate is None:
        problems.append("expected an overpayment estimate, got none")
    else:
        if estimate.amount_gbp != Decimal("419.00"):
            problems.append(f"expected £419.00, got £{estimate.amount_gbp}")
        if "if" in estimate.label.lower():
            problems.append(f"expected an unconditional label, got {estimate.label!r}")
    return problems


@case("Emergency M1, not told (CONDITIONAL)", "emergency_m1_midyear_start.pdf", None)
def _check_emergency_conditional(result):
    problems = []
    estimate = _estimate(result)
    if estimate is None:
        problems.append("expected a conditional overpayment estimate, got none")
    else:
        if estimate.amount_gbp != Decimal("419.00"):
            problems.append(f"expected £419.00, got £{estimate.amount_gbp}")
        if "only employment this tax year" not in estimate.label:
            problems.append(f"expected the condition in the label, got {estimate.label!r}")
    return problems


@case("Emergency M1, level pay (NO FIGURE)", "emergency_m1_level_pay.pdf", True)
def _check_level_pay(result):
    if _estimate(result) is not None:
        return ["level pay on M1 costs nothing - no estimate should be shown"]
    return []


def _run_case(label, fixture, only_job, check) -> list[str]:
    path = os.path.join(FIXTURE_DIR, fixture)
    with open(path, "rb") as handle:
        extract = extract_payslip(handle.read(), filename=fixture)
    result = analyse_payslip(extract, UserContext(only_job=only_job))

    if result.status != "ok":
        return [f"status was {result.status!r}: {result.failure_reason}"]
    return check(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    failures = 0
    for run in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"\n########## RUN {run} of {args.runs} ##########")
        for label, fixture, only_job, check in CASES:
            problems = _run_case(label, fixture, only_job, check)
            if problems:
                failures += 1
                print(f"FAIL  {label}  ({fixture}, only_job={only_job})")
                for problem in problems:
                    print(f"        {problem}")
            else:
                print(f"ok    {label}")

    print()
    print(f"{len(CASES) * args.runs - failures}/{len(CASES) * args.runs} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
