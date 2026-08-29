"""
Run the full pipeline against a directory of real payslip PDFs.

Usage:
    python verify/run_real_payslips.py /path/to/payslips

For each PDF: fields extracted, fields that failed the confidence gate,
findings raised, and the pound figure (if any) behind each finding.
Ends with: "N of M payslips produced a finding worth money".

Never copies, caches, or writes any payslip content to disk - files are
read directly from the path given and nothing derived from them is
persisted anywhere, including this script's own output going only to
stdout. Real payslips must never be committed to this repo; the
directory you point this at should live outside it, and IS_GITIGNORED
below (a defensive rule, not a promise about where you keep them) covers
the conventional locations in case one is used inside the repo by
mistake.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from slyp.analysis import analyse_payslip
from slyp.contract import AnalysisResult, UserContext
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from slyp.extraction import NotAPayslip, RedactionFailure, UnreadableDocument, extract_payslip


def _run_one(pdf_path: pathlib.Path) -> AnalysisResult | None:
    """Returns the AnalysisResult, or None if extraction itself failed
    (a hard failure before the calculation/findings layer ever runs).

    Deliberately broad about what it catches: one unreadable file in a
    batch of real payslips must not stop the run before it reaches the
    summary line."""

    print(f"\n{'=' * 70}")
    print(pdf_path.name)
    print("=" * 70)

    try:
        extract = extract_payslip(pdf_path.read_bytes(), filename=pdf_path.name)
    except UnreadableDocument as exc:
        print(f"  EXTRACTION FAILED (no usable text): {exc.reason}")
        return None
    except NotAPayslip as exc:
        print(f"  EXTRACTION FAILED (not recognised as a payslip): {exc.reason}")
        return None
    except RedactionFailure:
        print("  EXTRACTION REFUSED: the redaction gate would not clear this payload for sending")
        return None
    except PdfminerException as exc:
        # See main.py: pdfplumber wraps password-protected and corrupt/
        # malformed PDFs in this one exception type.
        inner = exc.args[0] if exc.args else None
        if isinstance(inner, (PDFPasswordIncorrect, PDFEncryptionError)):
            print("  EXTRACTION FAILED: password-protected PDF")
        else:
            print("  EXTRACTION FAILED: corrupt or malformed PDF")
        return None
    except PDFSyntaxError:
        print("  EXTRACTION FAILED: corrupt PDF (page content)")
        return None
    except Exception as exc:
        print(f"  EXTRACTION FAILED (unexpected: {type(exc).__name__})")
        return None

    print("  Fields extracted:")
    for field, value in (
        ("tax_code.value", extract.tax_code.value),
        ("period.frequency", extract.period.frequency),
        ("period.period_number", extract.period.period_number),
        ("pay.gross_this_period", extract.pay.gross_this_period),
        ("pay.gross_ytd", extract.pay.gross_ytd),
        ("deductions.income_tax", extract.deductions.income_tax),
        ("deductions.national_insurance", extract.deductions.national_insurance),
        ("deductions.student_loan", extract.deductions.student_loan),
        ("deductions.pension_employee", extract.deductions.pension_employee),
        ("net_pay", extract.net_pay),
    ):
        if field in extract.unreadable_fields:
            continue
        if value is not None:
            print(f"    {field}: {value}")

    print("  Fields that failed the confidence gate:")
    if extract.unreadable_fields:
        for field in extract.unreadable_fields:
            print(f"    {field}")
    else:
        print("    (none)")

    result = analyse_payslip(extract, UserContext(only_job=None))

    print(f"  Status: {result.status}")
    if result.failure_reason:
        print(f"  Failure reason: {result.failure_reason}")
    if result.verdict:
        print(f"  Verdict: [{result.verdict.severity}] {result.verdict.headline}")

    if result.findings:
        print("  Findings:")
        for finding in result.findings:
            print(f"    [{finding.severity}] {finding.title}")
            if finding.estimate:
                print(f"      -> £{finding.estimate.amount_gbp} ({finding.estimate.label})")
    else:
        print("  Findings: (none)")

    return result


def _finding_pound_total(result: AnalysisResult) -> Decimal:
    return sum(
        (f.estimate.amount_gbp for f in result.findings if f.estimate is not None),
        Decimal("0"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=pathlib.Path, help="Directory of payslip PDFs to check")
    args = parser.parse_args()

    directory: pathlib.Path = args.directory
    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    pdf_paths = sorted(directory.glob("*.pdf"))
    if not pdf_paths:
        print(f"No .pdf files found in {directory}", file=sys.stderr)
        sys.exit(1)

    total = len(pdf_paths)
    with_money_finding = 0

    for pdf_path in pdf_paths:
        result = _run_one(pdf_path)
        if result is not None and _finding_pound_total(result) > 0:
            with_money_finding += 1

    print(f"\n{'=' * 70}")
    print(f"{with_money_finding} of {total} payslips produced a finding worth money")
    print("=" * 70)


if __name__ == "__main__":
    main()
