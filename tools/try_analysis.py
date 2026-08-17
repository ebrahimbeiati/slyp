# tools/try_analysis.py
import pathlib, sys
from dotenv import load_dotenv
load_dotenv()
from slyp.extraction import extract_payslip
from slyp.findings import analyse, gate_report
from slyp.contract import UserContext

folder = pathlib.Path(sys.argv[1])
for pdf in sorted(folder.glob("*.pdf")):
    print("="*70); print(pdf.name); print("="*70)
    extract = extract_payslip(pdf.read_bytes(), filename=pdf.name)

    # Gating doesn't depend on only_job (it only ever changes R3's
    # phrasing/severity, never whether a check runs at all) - see
    # gate_report() - so this is the same regardless of the only_job
    # loop below and only needs printing once.
    print("\n--- gate report (which checks ran, which were gated, and why) ---")
    for entry in gate_report(extract):
        line = f"  [{entry['outcome']}] {entry['id']}"
        if entry["outcome"] == "gated" and entry["note"]:
            line += f" - {entry['note']}"
        print(line)

    for only_job in (None, True, False):
        result = analyse([extract], UserContext(only_job=only_job))
        print(f"\n--- only_job={only_job} ---")
        print(result.verdict.headline if result.verdict else result.status)

        if result.score:
            print(
                f"  score: {result.score.value} "
                f"(checks_passed={result.score.checks_passed}, "
                f"checks_run={result.score.checks_run})"
            )
            for mover in result.score.movers:
                print(f"    mover: {mover}")

        for f in result.findings:
            print(f"  [{f.severity}] {f.title}")
            print(f"      {f.explanation}")
            if f.estimate:
                print(f"      estimate - {f.estimate.label}: £{f.estimate.amount_gbp}")
            if f.next_step:
                print(f"      next step: {f.next_step}")
            print(f"      source_fields: {f.source_fields}")
