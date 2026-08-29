"""
Scratch diagnostic — NOT part of the shipped test suite.

Answers one question: why did period.period_number come back unreadable,
and therefore why did "We could not complete every calculation" show?

Those two are the same bug. _facts_from_extract() refuses to build the
calculation facts without a period number, analyse_payslip() catches
that as a calculation_error, and the findings layer turns it into the
"could not complete every calculation" advisory. Fix the period number
and both messages go away.

period.period_number is derived, never read off the page, and needs BOTH
a pay date and a confidently-read frequency. This prints which of the
two is missing.

This DOES call the extraction model (same provider/key as the app, from
.env), because the question is what the model returned. The payload it
sends is the same redacted, allowlisted payload the app sends - nothing
extra leaves the machine.

Run: python verify/diagnose_period_number.py path/to/payslip.pdf
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from slyp.extraction import (  # noqa: E402
    _call_model,
    _DATE_RE,
    _KNOWN_LABEL_RE,
    _period_number_plausible,
    _read_pdf,
    derive_period_number,
    financial_lines_only,
    redact,
)


def main(path: str) -> int:
    with open(path, "rb") as handle:
        pdf_bytes = handle.read()

    text, _pages = _read_pdf(pdf_bytes)
    redacted, _ = redact(text)
    payload = financial_lines_only(redacted)

    print("=" * 70)
    print("STEP 1 - what survived redaction and the allowlist")
    print("=" * 70)
    date_lines = [ln for ln in payload.splitlines() if _DATE_RE.search(ln)]
    print(f"lines reaching the model : {len(payload.splitlines())}")
    print(f"lines containing a date  : {len(date_lines)}")
    for line in date_lines:
        print(f"    {line.strip()!r}")
    if not date_lines:
        print("    NONE - no date survived, so pay_date cannot be read.")

    freq_lines = [
        ln
        for ln in payload.splitlines()
        if any(
            word in ln.lower()
            for word in ("month", "week", "frequenc", "period", "pay basis", "pay type")
        )
    ]
    print(f"lines mentioning a period/frequency term : {len(freq_lines)}")
    for line in freq_lines:
        print(f"    {line.strip()!r}")
    if not freq_lines:
        print("    NONE - nothing for the model to read a frequency from.")

    print()
    print("=" * 70)
    print("STEP 2 - what the model returned")
    print("=" * 70)
    extract = _call_model(payload)
    period = extract.period
    print(f"period.pay_date       : {period.pay_date!r}")
    print(f"period.frequency      : {period.frequency!r}")
    print(f"period.period_number  : {period.period_number!r}  (model's own read)")
    print(f"unreadable_fields     : {extract.unreadable_fields}")
    print(f"ambiguous_fields      : {extract.ambiguous_fields}")
    for field in ("period.pay_date", "period.frequency", "period.period_number"):
        if field in extract.confidence:
            print(f"confidence[{field}] = {extract.confidence[field]}")
    if extract.warnings:
        print("model warnings:")
        for warning in extract.warnings:
            print(f"    - {warning}")

    print()
    print("=" * 70)
    print("STEP 3 - why period_number was or wasn't derived")
    print("=" * 70)
    frequency_known = (
        period.frequency is not None
        and "period.frequency" not in extract.unreadable_fields
    )
    print(f"frequency_known : {frequency_known}")
    print(f"pay_date present: {period.pay_date is not None}")

    derived = (
        derive_period_number(period.pay_date, period.frequency)
        if frequency_known
        else None
    )
    print(f"derived value   : {derived!r}")

    if derived is not None:
        print("\nRESULT: derived fine. period_number is NOT the problem here.")
        return 0

    print("\nRESULT: could not derive. Cause:")
    if not frequency_known:
        if period.frequency is None:
            print("  -> FREQUENCY. The model returned no frequency at all.")
            print("     Check the 'period/frequency term' lines above: if the")
            print("     payslip never prints 'Monthly'/'Weekly' as a word, the")
            print("     model is right not to guess, and the frequency has to")
            print("     come from a printed period label ('Month 9', 'Week 39')")
            print("     instead. That inference does not exist yet.")
        else:
            print(f"  -> FREQUENCY read as {period.frequency!r} but flagged unreadable,")
            print("     so it isn't trusted.")
    elif period.pay_date is None:
        print("  -> PAY DATE. Frequency is known, but no pay date was read.")
        if date_lines:
            print("     A date DID survive to the model (see step 1), so this is")
            print("     the model failing to map it to pay_date, not redaction.")
        else:
            print("     No date survived redaction/allowlisting either - so the")
            print("     date never reached the model at all.")

    print("\n  Fallback (printed period label) also did not apply:")
    print(f"     model period_number : {period.period_number!r}")
    print(f"     frequency_known     : {frequency_known}")
    print(
        "     plausible for freq  : "
        f"{_period_number_plausible(period.period_number, period.frequency) if period.period_number is not None else 'n/a'}"
    )
    print("     (it requires pay_date to be absent AND frequency to be known)")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
