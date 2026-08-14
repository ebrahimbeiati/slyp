# tools/try_extraction.py
import json, pathlib, sys
from dotenv import load_dotenv
load_dotenv()

from slyp.extraction import extract_payslip

folder = pathlib.Path(sys.argv[1])
for pdf in sorted(folder.glob("*.pdf")):
    print("=" * 70)
    print(pdf.name)
    print("=" * 70)
    try:
        result = extract_payslip(pdf.read_bytes())
        print(result.model_dump_json(indent=2))
    except Exception as e:
        print(f"{type(e).__name__}: {e}")