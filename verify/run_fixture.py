"""
Run a fixture PDF through the real pipeline and print everything the demo
depends on: every finding, the estimate, unreadable_fields, and the score.

Calls the extraction model (same provider/key as the app, from .env), so
each run costs one API call. --runs N repeats the whole pipeline N times
and reports whether the estimate figure moved between runs.

    python verify/run_fixture.py verify/fixtures/emergency_m1_midyear_start.pdf
    python verify/run_fixture.py verify/fixtures/emergency_m1_midyear_start.pdf --runs 5

--only-job controls UserContext.only_job, which the emergency-code
overpayment estimate hard-gates on (findings.py
_emergency_code_overpayment_estimate, guard 1): anything other than an
explicit True withholds the figure entirely. Default true, since the
point of this script is to see the figure.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from slyp.analysis import analyse_payslip  # noqa: E402
from slyp.contract import UserContext  # noqa: E402
from slyp.extraction import extract_payslip  # noqa: E402


def _run_once(pdf_bytes: bytes, filename: str, only_job):
    extract = extract_payslip(pdf_bytes, filename=filename)
    return extract, analyse_payslip(extract, UserContext(only_job=only_job))


def _print_result(extract, result) -> None:
    period = extract.period
    print("-" * 68)
    print("EXTRACT")
    print(f"  status              : {result.status}")
    print(f"  employer_name       : {extract.employer_name!r}")
    print(f"  pay_date            : {period.pay_date}")
    print(f"  frequency           : {period.frequency}")
    print(f"  period_number       : {period.period_number}")
    print(f"  tax_year            : {period.tax_year}")
    print(f"  tax_code            : {extract.tax_code.value!r}")
    print(f"  gross this period   : {extract.pay.gross_this_period}")
    print(f"  gross ytd           : {extract.pay.gross_ytd}")
    print(f"  income tax          : {extract.deductions.income_tax}")
    print(f"  income tax ytd      : {extract.deductions.income_tax_ytd}")
    print(f"  national insurance  : {extract.deductions.national_insurance}")
    print(f"  ni ytd              : {extract.deductions.national_insurance_ytd}")
    print(f"  ni_category         : {extract.deductions.ni_category!r}")
    print(f"  pension employee    : {extract.deductions.pension_employee}")
    print(f"  net pay             : {extract.net_pay}")
    print(f"  reconciles          : {extract.reconciles}")
    print(f"  unreadable_fields   : {extract.unreadable_fields or '(none)'}")
    print(f"  warnings            : {extract.warnings or '(none)'}")

    print()
    print(f"VERDICT: {result.verdict.headline}  [{result.verdict.severity}]")
    score = result.score
    print(
        f"SCORE  : {score.value}  "
        f"({score.checks_passed}/{score.checks_run} checks passed)"
    )
    if score.movers:
        for mover in score.movers:
            print(f"         mover: {mover}")

    print()
    print(f"FINDINGS ({len(result.findings)})")
    for finding in result.findings:
        print(f"  [{finding.severity}] {finding.id}")
        print(f"      {finding.title}")
        print(f"      {finding.explanation}")
        if finding.next_step:
            print(f"      -> {finding.next_step}")
        if finding.estimate is not None:
            print(
                f"      *** ESTIMATE: {finding.estimate.label} = "
                f"£{finding.estimate.amount_gbp} "
                f"(is_estimate={finding.estimate.is_estimate}) ***"
            )
        print(f"      source_fields: {finding.source_fields}")
    print("-" * 68)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--only-job",
        choices=("true", "false", "unset"),
        default="true",
    )
    args = parser.parse_args()

    only_job = {"true": True, "false": False, "unset": None}[args.only_job]

    with open(args.pdf, "rb") as handle:
        pdf_bytes = handle.read()
    filename = os.path.basename(args.pdf)

    estimates = []
    for run in range(1, args.runs + 1):
        extract, result = _run_once(pdf_bytes, filename, only_job)
        if args.runs > 1:
            print(f"\n########## RUN {run} of {args.runs} ##########")
        _print_result(extract, result)
        estimates.append(
            next(
                (
                    f.estimate.amount_gbp
                    for f in result.findings
                    if f.estimate is not None
                ),
                None,
            )
        )

    if args.runs > 1:
        print()
        print("=" * 68)
        print("STABILITY")
        for run, amount in enumerate(estimates, start=1):
            print(f"  run {run}: {amount if amount is not None else '(no estimate)'}")
        unique = set(estimates)
        print(f"  distinct values across {args.runs} runs: {len(unique)}")
        print("  STABLE" if len(unique) == 1 else "  *** MOVED ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
