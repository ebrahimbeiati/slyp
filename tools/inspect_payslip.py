"""
Dev-only tool: inspect payslip PDFs to see what pdfplumber actually
extracts, before any extraction code gets written.

NOT part of the slyp package — never import this from slyp/. It exists so
a human can look at real payslip layouts (text layer or not, where labels
sit relative to their values, whether tables come back as tables) and
design extraction around what is actually there.

Usage:
    python tools/inspect_payslip.py <folder>

<folder> is required — there is no default, on purpose. This must never
run against a folder inside the repo by accident. samples/private/ is
already gitignored; that's the place to drop real payslips for this.

This script only reads PDFs and prints to stdout. It never writes a file
and never makes a network call. The printed output can contain real PII
(names, NI numbers, addresses) straight off the page — that is expected,
since a human is reading it locally. Do not paste raw output anywhere;
redact it first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pdfplumber

LABELS: dict[str, list[str]] = {
    "tax code": ["tax code"],
    "gross": ["gross"],
    "net": ["net pay", "net "],
    "national insurance": ["national insurance"],
    "PAYE / income tax": ["paye", "income tax"],
    "pension": ["pension"],
    "student loan": ["student loan"],
    "year to date / YTD": ["year to date", "ytd"],
    "employee number": ["employee number", "employee no", "emp no"],
    "NI number": ["ni number", "national insurance number"],
}

MAX_EXAMPLE_LINES = 5


def find_labels(text: str) -> dict[str, list[str]]:
    """For each known label, the lines in `text` that mention it."""
    lines = text.splitlines()
    hits: dict[str, list[str]] = {}
    for label, keywords in LABELS.items():
        matches = [
            line.strip()
            for line in lines
            if any(keyword in line.lower() for keyword in keywords)
        ]
        if matches:
            hits[label] = matches
    return hits


def inspect_pdf(path: Path) -> None:
    print("=" * 70)
    print(f"FILE: {path.name}")
    print("=" * 70)

    try:
        with pdfplumber.open(path) as pdf:
            page_texts: list[str] = []
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                page_texts.append(text)
                tables = page.extract_tables()

                print(f"\n--- page {i} ---")
                print(f"text layer: {'yes' if text.strip() else 'no'}")
                print("\nraw text:")
                print(text if text.strip() else "(no extractable text)")

                print(f"\ntables ({len(tables)} found):")
                for t_idx, table in enumerate(tables, start=1):
                    print(f"  table {t_idx}:")
                    for row in table:
                        print(f"    {row}")

            has_text_layer = any(t.strip() for t in page_texts)
            all_text = "\n".join(page_texts)
            label_hits = find_labels(all_text)

            print(f"\n--- summary: {path.name} ---")
            print(f"pages: {len(page_texts)}")
            print(f"has text layer: {has_text_layer}")
            print("labels found:")
            if not label_hits:
                print("  (none of the known labels matched)")
            for label, matched_lines in label_hits.items():
                print(f"  {label}:")
                for line in matched_lines[:MAX_EXAMPLE_LINES]:
                    print(f"    {line}")
                remaining = len(matched_lines) - MAX_EXAMPLE_LINES
                if remaining > 0:
                    print(f"    ... and {remaining} more")
    except Exception as exc:  # noqa: BLE001 - keep the batch going on a bad file
        print(f"FAILED to read {path.name}: {exc}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect payslip PDFs with pdfplumber (dev tool, read-only, "
            "no defaults)."
        )
    )
    parser.add_argument("folder", type=Path, help="Folder containing PDF files to inspect")
    args = parser.parse_args()

    folder: Path = args.folder
    if not folder.is_dir():
        sys.exit(f"Not a directory: {folder}")

    pdfs = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        sys.exit(f"No PDFs found in {folder}")

    for pdf_path in pdfs:
        inspect_pdf(pdf_path)


if __name__ == "__main__":
    main()
