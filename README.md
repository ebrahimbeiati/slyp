# Slyp

Slyp checks a UK payslip. You upload the PDF, and it works out what your income
tax, National Insurance and student loan deductions should have been for that
period and compares them against what was actually taken. What comes back is a
list of findings in plain English, and a message you can send to your payroll
team about anything that looks wrong.

## How it works

One HTTP endpoint does the work: `POST /analyse` in `main.py`. The request path
is a single linear function with no branch that can skip a step, in this order.

**Upload and validation.** The request is rejected before anything is parsed if
it is too large, if the file field is missing, if the body is empty, or if the
first bytes are not `%PDF-`. The type is decided by magic bytes, not by the
filename or the `Content-Type` header. The size limit is enforced three times:
a fast pre-check on `Content-Length`, a streaming limit as the body arrives, and
a final check on the actual bytes.

**Text extraction.** `pdfplumber` reads the text layer from an in-memory buffer.
There is no OCR and no temp file — Starlette's multipart parser is patched so
that a large upload cannot spill to disk.

**Redaction.** Names, addresses, postcodes, NI numbers, sort codes, account
numbers, employee reference numbers, email addresses and phone numbers are
replaced with tokens like `[NI]` and `[BANK]`. This runs *before* the allowlist
filter, and the order matters: on a real payslip an NI number and a currency
amount frequently share one line, so filtering first would keep the line for its
currency amount and carry the NI number along with it.

**Allowlist filter.** A line is kept only if it contains a currency amount, a
percentage, a date, a tax-code pattern, or a known payslip label. Everything
else is dropped unseen. This is a positive filter that shares no pattern with
the redaction step, so it catches what those patterns miss — an unlabelled name
on its own line has no shape a PII regex can anchor to, but it also has no
financial content, so it never survives.

**Fail-closed gate.** Immediately before the network call, the filtered text is
re-scanned. Two independent checks: one re-runs the PII patterns, and one masks
every numeric shape a payslip legitimately explains (currency, percentages,
dates, tax codes, decimal rates) and refuses if what remains contains an
unexplained run of digits. The second check does not know what an NI number
looks like, so it cannot share the first one's blind spot. If either fires, the
request is refused and no call is made.

**Model extraction.** The filtered text goes to an LLM through a forced tool
call against a fixed schema. There is no free-text path for the model to answer
through. The model's only job is to report what is printed on the document —
gross pay, the deduction figures, the tax code, the pay date — with a confidence
score per field. It does no arithmetic, and the schema gives it nowhere to do
any: there is no field for the tax year, no field for whether the payslip
reconciles, and no field for any expected figure.

**Deterministic calculation.** Everything numeric is computed in Python, in
`slyp/calculations.py`, using `Decimal` throughout. The tax year is derived from
the pay date. The period number is derived from the pay date and frequency. Tax
is computed cumulatively or on a week 1/month 1 basis according to the code.
Whether the payslip's own figures reconcile is computed, never asked.

**Findings.** `slyp/findings.py` compares the computed figures against the
printed ones and produces findings. It does the comparing; it does not do the
calculating. Every pound figure the user sees — including the overpayment
estimate on an emergency tax code — comes from this layer, not from the model.

The frontend renders what the API returns. It contains no tax constant and no
tax arithmetic at all.

## Design rules

**Code calculates, the model explains.** The model reads a document and reports
what it says. Python computes every number. This is enforced by the schema
rather than by convention — the model has no field to put a calculation in.

**A missing field means the rule does not run.** Extraction returns a per-field
confidence score, and anything below the threshold is nulled and listed in
`unreadable_fields`. A rule that depends on a field listed there does not run
at all. No finding is better than a wrong one, so nothing is estimated, defaulted
or hedged to fill a gap.

**Nothing personal leaves the machine.** Personal data is removed server-side,
before the model call, and the gate refuses rather than sending anything it is
not sure about.

**Nothing is stored.** The PDF exists in memory for the length of one request.
There is no database, no disk write and no temp file. Logs carry timings and
exception *type* names only — never extracted text, field values, findings or
figures. The analysis result is returned to the browser and kept in
`localStorage` on the user's own device.

## What it refuses to do

Refusing is the design, not a gap in it. In each of these cases the engine
raises a typed refusal and the API returns a status explaining why, rather than
producing a number that would look authoritative and be wrong.

- **Scottish (`S`) and Welsh (`C`) tax codes.** Different bands. Applying
  rest-of-UK rates to them would produce a confident wrong figure.
- **`K` codes.** These add notional pay rather than granting an allowance, and
  carry a regulatory cap on how much can be added.
- **Income above £100,000.** The Personal Allowance tapers away above that
  threshold. The engine does not model the taper, so past it the allowance it
  would apply is one the taxpayer does not have.
- **Any tax year other than 2026/27.** Rates and thresholds move. There is no
  bypass flag for this and it cannot be re-enabled by configuration.
- **A pay date it cannot determine.** Without one the tax year cannot be
  derived, and guessing "the current year" is the case where a wrong answer
  would be least likely to be noticed.
- **Unreadable fields.** Anything the extraction step was not confident about is
  discarded rather than used.

## Running it locally

Two services: the FastAPI backend and the Next.js frontend.

**Prerequisites:** Python 3.12 or newer, Node 20 or newer, and an API key for
one LLM provider.

**Environment.** Copy `.env.example` to `.env` and fill it in. `.env` is
gitignored; `.env.example` documents the variable names without values.

| Variable | Purpose |
| --- | --- |
| `SLYP_MODEL_PROVIDER` | `anthropic` or `openai`. Set it explicitly — the default is `anthropic`, which may not be the key you have. |
| `SLYP_EXTRACTION_MODEL` | Model name. Required when the provider is `openai`. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Whichever matches the provider. The server refuses to start without it. |
| `SLYP_CORS_ORIGINS` | Comma-separated frontend origins. Defaults to `http://localhost:3000`. |
| `NEXT_PUBLIC_API_BASE_URL` | Backend origin, no trailing slash. Defaults to `http://localhost:8000`. Read at **build** time, not runtime. |

**Backend first**, because the frontend needs its address:

```
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

`GET /health` should return `{"status":"ok"}`. If the process exits at startup
naming an environment variable, that is the configuration guard doing its job —
it refuses to boot rather than accept uploads it cannot analyse.

**Then the frontend:**

```
npm install
npm run dev
```

Open `http://localhost:3000`. With no `NEXT_PUBLIC_API_BASE_URL` set, it will
call `http://localhost:8000`, which is where the backend is above.

For deployment, see `BACKEND_HANDOFF.md`.

## Testing

```
python -m pytest tests/ -q     # 283 tests
npm test                       # 20 tests
```

The Python suite covers extraction and redaction (142), the calculation engine
(54), the findings layer (49), the analysis pipeline (24), the four demo
fixtures at the analysis layer (9), and the payslip inspection tool (5). None of
it makes a network call — the fixture tests exercise the analysis layer against
hand-built extracts, so the fast loop catches a logic regression without an API
key.

The frontend suite covers the API client, the only-job question mapping, and the
stored-result schema versioning.

There is also an end-to-end suite that makes **real model calls** against the
four demo fixtures, which is the only way to catch a redaction change that eats
a needed line or an allowlist gap:

```
python verify/run_regression.py
python verify/run_regression.py --runs 3     # stability across runs
```

`verify/` holds the verification work: an independent audit in
`verify/FINAL_REPORT.md`, and the scripts that produced it — payload
interception, a call-graph search for guards on dead code paths, event-loop
blocking measurement, and the fixture generators. Fixtures are synthetic and
generated by `verify/fixtures/make_fixtures.py`. No real payslip is in this
repository.

## Limitations

- **UK only**, and within the UK, England and Northern Ireland rates only.
- **One tax year**, 2026/27. Anything else is refused rather than approximated.
- **Text-layer PDFs only.** There is no OCR. A PDF with no text layer at all
  is caught in `_read_pdf` before redaction, the safety gate or the model call,
  so it costs no model round trip and is rejected in a few milliseconds with a
  message explaining that we do not read images yet.

  The partial case is not caught. A scan whose letterhead carries a text layer
  while the payslip body is an image has non-empty text, so it passes that check
  and is sent to the model, which then reports it cannot find the fields. The
  signal that would catch it already exists in the pipeline: the proportion of
  lines the allowlist filter keeps. Measured against the four fixtures, a real
  payslip keeps 9 or more lines and 73–82% of them, while a letterhead-only
  scan, OCR garbage and a stray-figure document each keep zero or one. Checking
  that between the filter and the gate would cost nothing and reuse tested code.

  It has not shipped because the threshold has only ever been measured against
  synthetic documents. A false positive means refusing a real payslip with a
  message saying it has no text when it plainly does, which is a much worse
  outcome than one wasted model call — so this waits for measurements against
  real payslips rather than fixtures we wrote ourselves.
- **One payslip at a time.** There is no concept of multiple jobs combined, and
  no history — the contract carries a single analysis, and the browser stores
  only the most recent one.
- **The user is asked one question** — whether they have had another job this
  tax year — because a single payslip cannot see whether the Personal Allowance
  is being used elsewhere. Answering "not sure" omits the field, and findings
  that depend on it stay conditional.
- **The emergency-code estimate assumes no previous employer this tax year.**
  Someone who changed jobs mid-year can truthfully say this is their only job
  while a previous employer has already used part of the allowance, which would
  make the figure an overstatement. The wording carries that condition.
- **`AnalysisResult.projections` is a contract field with no producer.** It is
  part of the published shape and is hardcoded to an empty list at every return
  site. The `Projection` and `ProjectionPoint` types exist and nothing fills
  them in.
- **Self-reported confidence is a signal, not a measurement.** The threshold
  that decides whether a field is trusted is a placeholder, not a value tuned
  against a corpus of real payslips.
- **Blocking I/O on the request path.** The endpoint is `async` but performs
  synchronous PDF parsing and a synchronous model call, so the server stalls for
  the duration of each request. Fine for one user at a time; not fine under
  concurrency.
