# Slyp — Final Verification Report

**Verified:** 2026-08-22, against `demo-ready` @ `5edb294` ("Add the BR and under-threshold
fixtures, and a regression suite over all four"). Working tree clean, no unpushed commits,
`origin/demo-ready` == local `HEAD`.

**Method:** execution, not reading. Full pytest suite, full `node --test` suite, a live
FastAPI server driven over HTTP, ~30 live model calls against the real provider, a
production `next build` with the emitted bundle grepped byte-wise, and purpose-built
adversarial fixtures. Every claim below that says PASS was produced by running something.
Everything I could not run is listed in **What I could not verify**, not quietly folded in.

**No real payslip was used.** Every fixture is synthetic and generated in-repo
(`verify/fixtures/make_fixtures.py`, `verify/final_privacy_payload.py`). I found no real
payslip committed anywhere in the repo or its history.

**Source changes:** the verification pass itself modified nothing. Two fixes were then made
on explicit request, each scoped to its finding and separately re-verified — **FR-05 (the
fake paywall)** and **FR-04 (the £100k Personal Allowance taper)**. Both are written up in
their own sections immediately below, including what else FR-04's fix changes. Everything
else in the findings table stands as originally verified. All scratch work is in
`verify/final_*`. `next-env.d.ts` is rewritten by `npm run build` and has been restored.

---

## Fix applied after verification — FR-05 (the fake paywall)

Requested and carried out after the report above was written. Nothing else was touched.

**Removed:**

- `app/page.tsx` — the `Insights` bottom-nav button, the entire "🔒 Premium Feature /
  Historical Pay Trend Analytics" modal (including the `Upgrade for £2.99/mo` button and its
  `alert("Sandbox: payment processing not active.")`), and the now-unused `premiumFeature`
  state. −39 lines.
- `components/prototype/PrototypeScaffold.tsx` — the "After 4 payslips" tab and its
  `alert("🔒 Premium Tier … requires an upgraded active subscription")`. −3 lines.

**Re-verified after a clean rebuild** (`rm -rf .next && npm run build`):

| Check | Result |
|---|---|
| Paywall strings in source (`app/`, `lib/`, `components/`) | **0** |
| `Premium Tier` / `Premium Feature` / `Multi-payslip timelines` / `Sandbox: payment processing` / `Upgrade for` / `After 4 payslips` / `Historical Pay Trend` in the built bundle | **0 files each** |
| `2.99` in the bundle | 13 files, **none the price** — all SVG path coordinates (`22.9999`), inspected directly |
| Served HTML at `/` for `Premium` / `Insights` / `Upgrade` / `After 4 payslips` | **0 occurrences each** |
| `npx tsc --noEmit` | clean |
| `npx eslint .` | 1 error + 1 warning — **unchanged**, both pre-existing (FR-08); no new problems |
| `npm test` | **20/20 pass** |
| `python -m pytest tests/` | **267/267 pass** |
| `npm run build`, routes `/` and `/upload` | build succeeds, both serve **200** |

**Deliberately not removed:** the "← Back / Next →" prototype footer, the single remaining
"First payslip" pill and the mock phone bezel. Those are prototype chrome, not a paywall,
and removing them changes the demo's layout — a call for you, not for me. Now tracked
as **FR-19**.

---

## FR-04: fix applied — the £100k Personal Allowance taper

Requested and carried out after the report above was written.

### The repro, before and after

A **correct** £150,000 payslip (£12,500/month, month 12, `1257L`, taxed exactly as HMRC
would with a fully tapered zero allowance):

| | Before | After |
|---|---|---|
| `status` | `ok` | **`unsupported`** |
| verdict | "2 things to check on this payslip" | "This payslip needs a manual check" |
| findings | `income_tax_differs_from_calculation` **£678.37**, `net_pay_differs_from_calculation` **£678.37** | none |
| score | 75 (3/4) | `None` |
| `failure_reason` | — | "This payslip is on course to earn more than £100,000 over the tax year. Above £100,000 the Personal Allowance is gradually taken away, and we do not yet work that out — so rather than show you a tax figure that assumes an allowance you may not have, we have not estimated one for this payslip." |

### What changed

**1. The guard moved onto the live entry point.** New
`calculations.assert_allowance_not_tapered(facts)`, called from `income_tax_due()`
immediately after `validate_pay_period_facts()` and the `NT` early return. It raises
`UnsupportedPayslip` — the same typed refusal as Scottish/Welsh codes, K codes and an
unsupported tax year. It does **not** compute a tapered allowance.

**Both bases are covered by one placement.** `income_tax_due()` is the single entry point;
`cumulative_income_tax_due()` dispatches to `non_cumulative_income_tax_due()` for a W1/M1/X
code, so neither branch is reachable from the request path without passing the guard first.
The original repro went through the **cumulative** path (`1257L`, `cumulative=True`); the
non-cumulative path was independently broken (`non_cumulative_income_tax_due` returned
£2,290.50 with no refusal) and is now covered and separately tested.

**2. Threshold basis: the annualised projection** — `annualise(gross_this_period,
gross_ytd, period_number, frequency)`. Reasoning, since the brief rightly flags this as the
easy thing to get wrong:

- **Year-to-date alone under-detects.** A £150,000 earner is only £75,000 in by month 6, so
  months 1–8 would sail through and be computed with a full allowance — exactly the
  wrong-figure window this guard exists to close. Pinned by
  `test_taper_guard_uses_annualised_pay_not_year_to_date`.
- **This period's gross × periods-in-year over-detects** for anyone who started mid-year,
  and throws away pay already banked.
- **`annualise()` is the basis the engine already uses** for the mirror-image question — is
  full-year pay set to land *under* the Personal Allowance (`analyse_payslip` step 4, feeding
  the under-allowance gate). Using one definition of "what this person is on course to earn"
  for both ends of the allowance is the consistent choice.

`annualise()` over-projects on a one-off bonus period. That direction is the safe one: it
can refuse a payslip that would have calculated fine (costing a finding) and never accepts
one that would calculate wrongly (costing a wrong number). A missing finding is fine, a
wrong one is not.

**3. Scoped to codes that actually grant an allowance.** BR, D0, D1 and 0T all carry
`free_pay_annual == 0` — there is no allowance to taper, and the banded arithmetic is
already correct at any income. Verified rather than assumed: `0T` on £150,000 returns
**£53,703.00**, exactly right (`test_zero_allowance_code_is_correct_at_high_income`).
Refusing those would refuse a calculation the engine gets right. K codes carry a negative
allowance and are already refused in `parse_tax_code()`, so they never arrive. `NT` is
checked first and still returns zero — exempt outright, allowance irrelevant.

**4. The dead guard was deleted, not kept.** `annual_income_tax()` held the file's only
£100k refusal and had **zero callers and zero tests** — the project suite never referenced
it. Also deleted: `taxable_income()` (called only by `annual_income_tax()`) and
`personal_allowance_for_income()` (zero callers). The last one matters most: a live function
that computes a tapered allowance, in an engine whose rule is to *refuse* the taper, is an
invitation to wire it in and start producing the exact figures this engine promises not to
produce. `PERSONAL_ALLOWANCE_TAPER_START` is retained — it is now the live guard's
threshold. A comment block at the old site records why all three are gone, and
`test_the_dead_annual_tax_functions_are_gone` fails if any returns.

**5. The refusal now reaches the user.** This was necessary, and it is the one change that
goes beyond the taper, so it is called out rather than buried: `analyse_payslip` step 4
caught `UnsupportedPayslip` under a bare `except Exception` and reduced it to
`calculation_error`, which is used only as a boolean — the message was **discarded** and the
user got the generic "We could not complete every calculation". `UnsupportedPayslip` is now
caught separately and returned as `status="unsupported"` with its own `failure_reason`, the
same door the tax-year and tax-code refusals already leave by, and the shape `app/page.tsx`
already renders (`verdict.headline` + `failure_reason`, page.tsx:263-267).

**Other behaviour this changes:** the only other `UnsupportedPayslip` reachable in step 4 is
an **unsupported NI category** from `validate_pay_period_facts()`. It moves from
"We could not complete every calculation" (`status="ok"`, advisory finding) to
`status="unsupported"` naming the category. That is an improvement and consistent with every
other refusal, but it is a behaviour change you did not explicitly ask for — say the word and
I will narrow the catch to the taper alone.

### Tests — 16 added, all passing

`tests/test_calculations.py` (12):
`test_the_150k_repro_from_the_final_report_refuses` (**pinned by name**, and asserts the
message names £100,000 and the Personal Allowance) · `..._just_under_the_taper_threshold_still_calculates`
(£99,996) · `..._just_over_the_taper_threshold_refuses` (£100,008 — £12 over, pins the
boundary itself) · `..._exactly_at_the_threshold_still_calculates` (£100,000 is not *above*)
· `..._applies_on_the_cumulative_path` · `..._applies_on_the_non_cumulative_path` ·
`..._uses_annualised_pay_not_year_to_date` · `..._does_not_refuse_a_zero_allowance_code` ·
`..._zero_allowance_code_is_correct_at_high_income` · `..._nt_is_answered_not_refused_at_high_income`
· **`test_the_taper_guard_is_reachable_from_income_tax_due`** (asserts through
`income_tax_due()` *and* `calculate_pay_breakdown()` — what `analyse_payslip` actually calls
— so the guard cannot drift back onto a dead path) · `test_the_dead_annual_tax_functions_are_gone`.

`tests/test_analysis.py` (4): `test_the_150k_repro_returns_unsupported_not_a_finding`
(**pinned by name**) · `..._no_longer_produces_any_pound_figure` ·
`..._a_high_earner_on_a_zero_allowance_code_is_still_analysed` ·
`..._an_ordinary_payslip_is_unaffected_by_the_taper_guard`.

### Verification

| Check | Result |
|---|---|
| `python -m pytest tests/` | **283 passed** (was 267; +16, no regressions) |
| `python verify/run_regression.py` — all four demo fixtures, **live model calls** | **5/5 passed**, £419.00 unchanged |
| `npm test` / `npx tsc --noEmit` | 20/20 · clean |
| `npx eslint .` | 1 error + 1 warning — **unchanged**, both pre-existing (FR-08) |
| Refusal message encoding over JSON | clean UTF-8, both `£` signs intact |

---

## Deployment: what is ready, and what is still yours to do

FR-01's config half is done; the deploy itself needs your accounts. Target chosen: **Railway
for the API, Vercel for the frontend.**

### Written and verified

| Artefact | What it does | Verified how |
|---|---|---|
| `Dockerfile` | Builds the API only — deps, `main.py`, `slyp/`. Explicit because this repo has `package.json` and `requirements.txt` at the root, and auto-detection picks Node, builds the frontend and never starts the API | Reviewed; **not built** — no Docker on this machine. Flagged below |
| `.dockerignore` | Keeps `.env`, the frontend, tests and `verify/` out of the image | Reviewed |
| `railway.json` | Pins the Dockerfile builder; `/health` check with a 300s timeout, generous because FR-06's blocking I/O can stall `/health` for ~2.3s mid-upload | Reviewed |
| `main.py` startup guard | Refuses to boot without the selected provider's key (FR-03) | **Executed both ways** — no key → `RuntimeError` naming the variable; key present → boots |
| `next.config.ts` build guard | Throws on a hosted build with no `NEXT_PUBLIC_API_BASE_URL`; rejects a trailing slash (FR-02) | **Executed four ways** — local build passes; `VERCEL=1` without the var fails with the explanation; with it, builds and bakes in the real URL; trailing slash rejected |
| `BACKEND_HANDOFF.md` | Every variable, the deploy order, a verification script, known issues | The file the brief's item 43 referred to, which did not exist |

Re-verified after all of it: **283 Python tests**, **20 frontend tests**, `tsc` clean, clean
production build, server starts, and the demo fixture still returns **£419.00, 4/4** end to
end over HTTP.

### Still yours — I cannot do these

No deployment CLI is installed here (no `vercel`, `railway`, `flyctl`, `docker`, `gh`), and
these need your accounts:

1. **Railway** → deploy from `ebrahimbeiati/slyp`, branch `demo-ready`; set
   `SLYP_MODEL_PROVIDER`, `SLYP_EXTRACTION_MODEL`, `OPENAI_API_KEY`, `SLYP_CORS_ORIGINS`;
   generate a domain.
2. **Vercel** → same repo and branch; set `NEXT_PUBLIC_API_BASE_URL` to the Railway domain;
   deploy.
3. Put the Vercel domain into Railway's `SLYP_CORS_ORIGINS` and **redeploy the API** (it
   reads that at import time).
4. Run the verification script in `BACKEND_HANDOFF.md` against both URLs.

Order matters and is circular by nature: API → its domain into the frontend → the frontend's
domain into CORS → redeploy the API.

### The risk I want named before you start

**The Dockerfile has never been built.** There is no Docker on this machine, so Railway's
first build is its first real test. It is deliberately minimal and every dependency ships
manylinux wheels for CPython 3.12, but *do this today, not on the 27th* — a first-build
failure is calm to fix with five days in hand and not calm to fix with five minutes.

Once both services are up, these currently-UNVERIFIED items become checkable and are worth
actually running: item 37 (cold start after 30+ min idle), item 44 (CORS, upload size and
timeout **against production**), item 45 (the full path in a browser against production),
and item 5 (deployed commit equals `HEAD`).

---

## Stranded-guard audit — has any other refusal been left on a dead path?

**Nothing fixed here. Reporting only, as asked.**

Method: `verify/final_stranded_guards.py` builds a real call graph from the two request-path
entry points in `main.py` by walking the AST for call nodes across all of `slyp/`, then lists
every function containing a `raise` of `UnsupportedPayslip`, `RedactionFailure`,
`NotAPayslip`, `UnreadableDocument` or `ValueError` and marks whether the graph reaches it.
Not a grep — FR-04 was invisible to grep precisely because the guard *existed*.

### Every refusal in the engine: 13 guard-bearing functions, 0 genuinely stranded

`parse_tax_code` (Scotland/Wales/K/unparseable) · `validate_tax_year` · `validate_pay_period_facts`
(NI category, Scottish region, ranges) · `assert_allowance_not_tapered` (new) ·
`national_insurance_due` · `student_loan_due` · `_facts_from_extract` · `assert_safe_to_send` ·
`_read_pdf` · `extract_payslip` · `_call_anthropic_model` · `_call_openai_model` — **all
reachable**.

The one the tool flagged, `types.py:__post_init__` (the `PayPeriodFacts` period-number range
check, FR-12), is a **false positive**: `@dataclass` calls it implicitly, so there is no call
node to find. I confirmed by execution earlier that it fires live —
`PayPeriodFacts(period_number=53, weekly)` raises. **So every refusal named in the brief —
Scotland, Wales, K codes, unsupported tax year, unparseable codes — is on the live path.
FR-04 was the only stranded guard.**

### But the same *shape* of hazard exists one layer up, and it is worse than a stranded guard

**`findings.build_analysis_result()` is a complete parallel response builder with no
callers — and its docstring actively invites wiring it in:** *"This is the main function the
API route can call after extraction and calculation have completed."* It is not what the API
route calls (`main.py` calls `analysis.analyse_payslip`). If anyone believes that docstring,
they get a pipeline that:

- **Uses a different, older scorer.** `findings.calculate_score()` — reachable only from
  `build_analysis_result()` — returns **`100, 0, 0, []` when there are no findings**.
  Demonstrated side by side: on an empty extract, `analysis.build_score()` returns
  `value=None, 0/0` with 4 not-applicable reasons, while `findings.calculate_score()` returns
  **score 100**. That is precisely the bug commit `d391c24` ("Stop counting a check with
  nothing to check as a check that passed") fixed on the live path — still sitting here,
  unfixed, in the abandoned copy. It also scores by penalty (100 − 25/action − 10/advisory)
  rather than passed-over-run, and counts `checks_run = len(findings)`.
- **Never calls `validate_tax_year`** — the tax-year guard (item 26) is bypassed entirely.
- **Never calls the calculation engine at all.** It takes `comparison` as a *parameter*, so
  `income_tax_due()`, and therefore the taper guard just added, is never reached.
- Uses a second `build_verdict` with a different signature (`findings.build_verdict(findings)`
  vs `analysis.build_verdict(findings, extract)`).

So the codebase contained two response builders, two scorers and two verdict builders. One
set had this week's fixes; the other did not, and was the one the docstring pointed a
newcomer at.

**DELETED on request** (commit `7e6165b`): `build_analysis_result()`, `calculate_score()`,
`findings.build_verdict()` and its private `_finding_count_headline()` helper — 167 lines.
Confirmed beforehand that the cluster was closed: `findings.build_verdict` was called only
from `build_analysis_result`, `calculate_score` only from `build_analysis_result`, and
`build_analysis_result` from nowhere. `analysis.build_verdict(findings, extract)` — the live
one, different signature — is untouched and still resolves locally in `analysis.py`.
A note at each deletion site records why, so they do not grow back.

Re-verified after: all modules import, **283 tests pass**, the live four-fixture regression
is **5/5**, and a re-run of this audit shows **no guard stranded by the deletion** (still 13
guard-bearing functions, all reachable bar the `__post_init__` false positive). Two new dead
private helpers appeared — `findings._is_not_a_payslip` and
`findings._has_critical_unreadable_fields`, previously called only by the deleted builder.
Neither holds a refusal. Left in place; flag if you want them gone too.

### Other orphans found (none holds a refusal)

| Function | Module | Note |
|---|---|---|
| `build_analysis_result`, `calculate_score`, `build_verdict` | `findings.py` | The parallel pipeline above — **the one worth acting on** |
| `analyse` | `analysis.py` | Harmless thin wrapper delegating to `analyse_payslip`; no divergent logic |
| `any_unreadable` | `analysis.py` | One-line helper, unused |
| `calculate_expected_net`, `calculate_from_values`, `explain_calculation` | `calculations.py` | Unused. `calculate_from_values` and `explain_calculation` do route through `income_tax_due`, so they inherit the new guard rather than bypassing it |
| `run_self_checks` | `calculations.py` | **Already broken at `HEAD`, independently of any change here — and deliberately left that way.** `python -m slyp.calculations` dies with `UnsupportedPayslip: K tax codes are outside the MVP: K475` — the self-checks expect `K475` to parse, but `parse_tax_code` refuses K codes. Verified pre-existing by stashing all changes and re-running. It is not on the request path, nothing calls it, and `pytest` is the real suite (283 passing), so fixing it five days out buys nothing. **Known and accepted, not missed.** Either correct the expectation or delete the script after the 28th; until then, do not run it expecting a green tick |
| `_looks_like_an_unambiguous_date`, `_sub` | `extraction.py` | False positives — passed as references (`skip_if=`, `pattern.sub()`), not called by name. Both live |
| `grants_allowance`, `is_emergency_basis`, `net`, `total_deductions` | `types.py` | All `@property`, so accessed as attributes rather than called. Genuinely unreferenced, but harmless |

---

## Headline, before the table

The system is in far better shape than the previous report (`verify/REPORT.md`,
`d538c36`) describes. That report's F1–F6 are **all fixed and independently re-verified**:
there is now a real HTTP backend, every module imports, `267/267` Python tests and `20/20`
frontend tests pass, the NI-number-with-periods and sort-code-with-slashes redaction
bypasses are closed, and the frontend's rival Scottish tax engine is gone from both source
and bundle.

Two things are nevertheless true and neither is soft. (A third — a fake paywall shipping in
the production build — was found by this pass and has since been deleted at your request;
see **FR-05** and *Fix applied*.)

**1. Rule 2 was disproved, and I could show you the payslip that did it.** On a *fully
correct* £150,000 payslip, Slyp reported "2 things to check", scored it 75/100, and told
the user their employer had under-deducted **£678.37** of income tax. It had not refused; it
had produced a confidently wrong pound figure. The refusal that should have prevented this
lived in `annual_income_tax()` — a function with **zero callers**. This is FR-04, and it has
since been **fixed at your request**: the guard now sits on `income_tax_due()`, the dead copy
is deleted, and 16 tests pin it. See *FR-04: fix applied*. Rule 2 now holds everywhere I can
test it.

**2. Nothing is deployed.** No deploy config of any kind exists — no `vercel.json`, no
Dockerfile, no Procfile, no CI, no `BACKEND_HANDOFF.md` (item 43 names a file that is not
in the repo). The demo today requires two processes started by hand on the build machine.
Worse, the production build already made has `http://localhost:8000` **baked into a
shipped JavaScript chunk**, and `NEXT_PUBLIC_*` is inlined at build time — so setting that
variable in a hosting platform's runtime environment will not fix it. This is FR-01/FR-02.

The three architectural rules, judged: **Rule 1 proved. Rule 3 proved. Rule 2 disproved**
(details in the final section).

---

## Findings

| ID | Sev | Component | What's wrong | Evidence | Suggested fix |
|----|-----|-----------|--------------|----------|---------------|
| **FR-01** | **P0** → config **DONE**, deploy **PENDING** | Deployment | Nothing was deployed and no deployment configuration existed. No `vercel.json` / Dockerfile / Procfile / `.github` / `BACKEND_HANDOFF.md`. `README.md` is untouched `create-next-app` boilerplate. Every deployed-URL check in Phases 6–7 is therefore UNVERIFIED. | `find` for all deploy configs → 0 hits. `ls BACKEND_HANDOFF.md` → no such file. `grep -niE 'deploy|vercel|render' README.md` → only create-next-app boilerplate. | **Config now written** (Railway + Vercel): `Dockerfile`, `.dockerignore`, `railway.json`, `BACKEND_HANDOFF.md`. **Nothing is deployed yet** — that needs your Railway and Vercel accounts. See *Deployment: what is ready* below. |
| **FR-02** | ~~P0~~ **FIXED** | `lib/Api.ts` + build | `NEXT_PUBLIC_API_BASE_URL` is inlined at **build** time. The production build in `.next/` right now has `http://localhost:8000` baked into a shipped chunk. Deployed as-is, every visitor's browser calls `localhost:8000` — which fails, and on an HTTPS page is additionally blocked as mixed content. Setting the var in a platform's *runtime* env does nothing. | `grep -rlo 'localhost:8000' .next/static/chunks/` → `43g6cwpgel_pj.js`. `lib/Api.ts:8`. | `next.config.ts` now **throws** on a hosted build (`VERCEL`/`CI` set) when the variable is absent, and rejects a trailing slash. Local builds unaffected. Verified all three ways; with the variable set, the real URL is baked in and `localhost:8000` is gone from the bundle. |
| **FR-03** | ~~P0~~ **FIXED** | `slyp/extraction.py`, `main.py` | Two env vars fail **silently and look identical to a healthy server**. (a) `SLYP_MODEL_PROVIDER` unset defaults to `anthropic`/`claude-sonnet-5`; `anthropic.Anthropic()` constructs fine with no key, so the process starts, `/health` returns 200, and the **first upload** dies as a generic 500. (b) `SLYP_CORS_ORIGINS` defaults to `http://localhost:3000`; unset on a real domain, every request is CORS-blocked and the UI says "Couldn't reach the server." | `env -u SLYP_MODEL_PROVIDER python -c 'from slyp import extraction'` → `provider defaults to: anthropic`, anthropic client constructs with no key. CORS preflight from an unlisted origin → `400`, no `access-control-allow-origin`. `extraction.py:789`, `main.py:83`. | `main.py` now **refuses to boot** without the selected provider's key, naming the variable, and logs a startup warning when `SLYP_CORS_ORIGINS` is unset. Verified both ways: no key → `RuntimeError`, key present → boots. The check is in `main.py` not `extraction.py` because the test suite imports the latter. |
| **FR-04** | ~~P1~~ **FIXED** | `slyp/calculations.py` | **The £100k personal-allowance taper gap was open.** `income_tax_due()` — the single live entry point — applies the full £12,570 allowance above £100k instead of refusing. `validate_pay_period_facts()` has no income check. The only refusal lives in `annual_income_tax()`, which has **zero callers anywhere** (dead code). Directly disproves Rule 2. | `verify/final_rule2_checks.py`: `annual_income_tax(150000)` → REFUSED; `income_tax_due(facts)` → **returned £5,153.62**, `non_cumulative_income_tax_due` → £2,290.50, no refusal. End-to-end: a fully correct £150,000 payslip yields "2 things to check", score 75, and an `income_tax_differs_from_calculation` finding claiming **£678.37** under-deducted. | **Fixed on request** — guard moved onto the live entry point, dead copy deleted, 16 tests added. See *FR-04: fix applied* below. |
| **FR-05** | ~~P1~~ **FIXED** | `app/page.tsx`, `components/prototype/PrototypeScaffold.tsx` | A **fake paywall shipped in the production build**. "Insights" — one of only two bottom-nav buttons on the results screen — opened a "🔒 Premium Feature / Historical Pay Trend Analytics / **Upgrade for £2.99/mo**" modal whose button fired `alert("Sandbox: payment processing not active.")`. The scaffold's "After 4 payslips" tab fired `alert("🔒 Premium Tier … requires an upgraded active subscription")`. | Strings `Premium Tier`, `Premium Feature`, `Multi-payslip timelines require an upgraded active subscription` all found in `.next/static/chunks/`. Served HTML at `http://localhost:3000/` contained `After 4 payslips`. `app/page.tsx:454,500-528`; `PrototypeScaffold.tsx:61`. | **Removed on request** — see *Fix applied* below. Remaining prototype chrome ("← Back / Next →", the `href="#"` dead link on `/upload`, the phone bezel) is **not** part of the paywall and was deliberately left alone; it is now tracked as **FR-19**. |
| **FR-19** | P2 | `components/prototype/PrototypeScaffold.tsx` | Prototype navigation chrome still renders in the production build: a "← Back / Next →" footer outside the phone bezel, where `Next →` on `/upload` is a dead `href="#"`; a now-single-item "First payslip" segmented control; and the mock phone frame itself. Split out of FR-05, which covered the paywall. | Served HTML contains `First payslip`, `Next →`, `← Back`. `PrototypeScaffold.tsx:50-92`; `app/upload/page.tsx:94` passes `nextHref="#"`. Separately, the `First payslip` link's `className` contains a flattened, broken ternary — the literal text `" : "text-gray-400 hover:text-[var(--ink)]"}` ends up inside the class attribute. | Not a correctness or privacy issue, and not a paywall — but it is prototype scaffolding on a screen judges will look at. Decide deliberately before the 28th rather than shipping it by default. |
| **FR-06** | **P1** | `main.py:147` | `async def analyse` performs blocking I/O (pdfplumber + the **synchronous** OpenAI client) directly on the event loop. The whole server stalls for the duration of every model call. | `verify/final_eventloop.py`: `/health` = **18 ms** idle, **2,309 ms** while an upload is in flight. Concurrent uploads serialise (8.45 s vs 3.98 s). | A platform health check with a short timeout will mark the instance unhealthy *during your demo upload* and restart it. Fix: `from starlette.concurrency import run_in_threadpool` and `await run_in_threadpool(extract_payslip, pdf_bytes, filename=filename)` (and the same for `analyse_payslip`). |
| **FR-07** | **P1** | `slyp/findings.py`, `slyp/analysis.py` | **One wrong figure is reported as two problems.** When `reconciles is True` (the only condition under which `expected_net` is populated), `net_difference` is *algebraically identical* to the sum of the component differences — so `_check_net_pay` can only ever restate `_check_income_tax`/`_check_national_insurance`. The verdict headline counts both. | `verify/final_netpay_check.py` CASE B: one £50 income-tax discrepancy → `income_tax_differs_from_calculation` **£50.00** *and* `net_pay_differs_from_calculation` **£50.00**, headline "**2 things to check on this payslip**". Same effect in the FR-04 £150k case (£678.37 twice). | Suppress `_check_net_pay` when any component finding already fired; keep it only for its genuinely independent case (several sub-£1 component differences summing over the £1 threshold). |
| FR-08 | P2 | `app/page.tsx:158` | **The pre-existing eslint error is still present** (item 32), plus an unused-var warning. It does *not* block the build — Next 16 no longer lints during `next build` — so it will not be caught by CI-by-accident. | `npx eslint .` → `1 error, 1 warning`; `react-hooks/set-state-in-effect` at `app/page.tsx:158`. `npm run build` succeeds regardless. | Move the `decodeStoredResult` read into `useState`'s lazy initialiser, or accept and silence it. |
| FR-09 | ~~P2~~ **FIXED** | `app/page.tsx` | **CLEAR-severity findings were not separated** (item 31). All findings render under "What we found" regardless of severity, beneath a headline that can read "Nothing obvious needs checking". **This is live on a demo fixture.** | Live API, `br_second_job.pdf` + `only_job=false`: verdict `Nothing obvious needs checking`, findings `[('tax_code_br_multiple_jobs', 'clear')]`. The UI renders that under "What we found". | **Fixed on request:** CLEAR findings now render under "What we confirmed", after "What we found"; each section renders only when non-empty, so an all-CLEAR result shows "What we confirmed" alone. Grouping only — `FindingCard` untouched. Confirmed against all four fixtures with live calls; the copy-for-payroll message is byte-identical before and after. |
| FR-10 | P2 | `slyp/analysis.py` `build_score` | `contract.py` states "`reconciles` False means treat every figure as suspect." It does not. Income-tax and NI checks still run and still count as **passes** on a payslip whose own arithmetic is broken. | Live API, deliberately non-reconciling payslip: `reconciles=false`, finding `payslip_does_not_reconcile`, and **score 75 (3/4)**. | Either stop counting deduction checks as passes when `reconciles is False`, or soften the claim in `contract.py`. Right now code and contract disagree. |
| FR-11 | P2 | `lib/payrollMessage.ts:83` | `result.findings.filter((f) => f.estimate !== null)` lets `undefined` through, then dereferences `finding.estimate!.label`. Latent only: the live API always emits `"estimate": null`, so it cannot fire today. It fires the moment anyone adds `exclude_none` to the response. | `verify/final_payroll_message.test.ts` — 9/10 pass; the deliberate "estimate key absent" case throws `TypeError: Cannot read properties of undefined (reading 'label')`. Confirmed live API emits the key with value `null`. | `f.estimate != null` (loose), or just `f.estimate`. One character. |
| FR-12 | P2 | `slyp/extraction.py` / `slyp/types.py` | Week 53 is unreachable. `derive_period_number()` deliberately returns 53 for the tax year's last days; `PayPeriodFacts.__post_init__` then rejects anything above 52. A week-53 payslip gets no calculation at all. | `derive_period_number(2027-04-05, weekly)` → `53`; `PayPeriodFacts(period_number=53, weekly)` → `ValueError: period_number 53 out of range for weekly pay (expected 1-52)`. | Consistent with "refuse rather than approximate", so not wrong — but it is a guaranteed annual dead end, and worth a deliberate decision rather than an accident of two functions disagreeing. Irrelevant on 28 August. |
| FR-13 | P2 | repo-wide | Dead and actively misleading code. (a) ~915 commented-out lines in `findings.py` (34% of the file) from an abandoned design. (b) `calculations.py` opens with a fully commented-out module header reading "**ALL PLACEHOLDERS, REPLACE FROM GOV.UK**" — it describes dead `RATES`, not the live constants, but it is the first thing anyone reading the tax engine sees. (c) `verify/patched_pkg/` is a **committed** stale duplicate of the entire `slyp` package from the previous audit. (d) `contract.py:292` documents `is_example_data` as "True for `/api/mock/scan`" — no such endpoint exists. | `grep -c '^# ' slyp/findings.py` → 915. `sed -n '1,60p' slyp/calculations.py`. `git ls-files verify/patched_pkg` → 7 tracked files. | Delete (a), (c); fix the comment in (b) and (d). Item 30's specific asks — `CalculationComparison`/`compare_with_payslip()` in `calculations.py` and `tools/try_analysis.py` — **are already gone** and only survive inside `verify/patched_pkg/`. |
| FR-14 | P2 | `app/upload/page.tsx:75` | `stopSweep()` is never called on the success path, so the 900 ms progress interval leaks past `router.push("/")` and keeps calling `setSweepIndex` indefinitely. | `runUpload()` — `stopSweep()` appears only in the `catch`. There is no `useEffect` cleanup for `sweepTimer`. | Call `stopSweep()` before `router.push("/")`, or clear the timer in a `useEffect` cleanup. Harmless today (the step index is clamped), but it is a leaked interval. |
| FR-15 | P2 | `slyp/extraction.py` | Two small label gaps (item 21). `_KNOWN_LABEL_RE` has no `pay day`, and `_PAY_DATE_LABEL_RE` does not recognise `Date of Payment`. | `verify/final_allowlist_period.py`: `'Pay Day Friday'` → DROPPED by the allowlist; `'Date of Payment 28/08/2026'` → allowlist KEEPS it but `read_pay_date_from_label` → `None`. | Near-harmless: any "Pay Day" line carrying an actual date is kept **and** read correctly (verified for `28/08/2026`, `28-08-2026`, `2026-08-28`, `28 August 2026`), and `Date of Payment` still reaches the model. Add both to the patterns anyway — one word each. |
| FR-16 | P2 | `main.py` oversize path | The 413 is returned before the request body is consumed. A client still streaming the upload can see a connection reset instead of the friendly message. | Python `urllib` on an 11 MB upload → `ConnectionAbortedError [WinError 10053]`, while the server logged a correct `413` in 0.000s. `curl` on the same upload → clean `413` + `"That file is too large…"` in 2 ms. | Well-behaved clients (curl, and browsers in practice) get the message. Listed for completeness; not worth changing before the demo. |
| FR-17 | P2 | `slyp/analysis.py:170-208` | An exception raised *after* `calculate_pay_breakdown()` succeeds (e.g. from `annualise()` or `cumulative_tax_due_to_date()`) is swallowed into `calculation_error`, but because `breakdown is not None` the `calculation_unavailable` finding is **never added**. The user is told nothing. | Code path: `except Exception as exc: calculation_error = str(exc)` at :205, then `if breakdown is not None:` at :210 takes the branch that ignores `calculation_error`. | Degrades safely today (the dependent findings gate themselves off a `None` comparison, so no wrong number is produced) — but it is a silent swallow. Add the `calculation_unavailable` finding whenever `calculation_error` is set, regardless of `breakdown`. |
| FR-18 | P2 | `slyp/findings.py` `_check_net_pay` | `estimate.amount_gbp` is not quantised to 2dp on the net-pay finding — the API emits `678.3700`. Displays correctly (the UI's `gbp()` clamps to 2dp) but violates the codebase's own Decimal-money discipline. | FR-04 repro: `Difference from calculated net pay = GBP 678.3700`. | Wrap in `money()` like every other figure. |

FR-02 and FR-03 were P0 conditional on deploying; both are now fixed, so deploying is safe
to attempt. FR-01 remains open until the services actually exist — see *Deployment: what is
ready* below.

---

## Phase-by-phase results

### Phase 1 — architecture and flow

- **Item 1–2 — PASS.** The path is a single linear function with no branch that can skip a
  step. Verified by introspecting the real source at runtime
  (`verify/final_gate_and_logging.py`), which recovered the call order from
  `extract_payslip` itself: `_read_pdf` → `redact(` → `financial_lines_only` →
  `assert_safe_to_send` → `_call_model`. In front of that, `main.py` enforces, in order:
  content-length pre-check → `max_part_size` streaming limit → file-field present →
  non-empty → actual byte length → **magic bytes** `%PDF-`. All six verified live over
  HTTP.
- **Item 3 — PASS.** Exactly two model call sites exist (`extraction.py:848` Anthropic,
  `:888` OpenAI), both reached only through `_call_model()`, which has exactly one caller:
  `extract_payslip:1374`, three lines after the gate. The payload is `filtered_text` plus a
  fixed system prompt and the `_ModelExtract` JSON schema. Not the filename, not the
  `RedactionMap`, not `UserContext`.
- **Item 4 — see FR-13.** Nothing on the executing path is a stub; the dead code is
  commented out, not reachable.
- **Item 5 — PASS locally / N/A remotely.** `HEAD` = `5edb294`, working tree clean,
  `origin/demo-ready..HEAD` empty. There is no deployment to compare against (FR-01).

### Phase 2 — Rule 1: code calculates

- **Item 6 — PASS.** Every numeric field in a live response traced
  (`verify/final_number_provenance.py`). Model-sourced numbers are **transcriptions only**
  (`gross_this_period`, `gross_ytd`, `income_tax`, `income_tax_ytd`, `national_insurance`,
  `national_insurance_ytd`, `pension_employee`, `net_pay`) plus self-reported confidence
  scores, which are never rendered as money. Every *derived* number — `score.value`,
  `checks_passed`, `checks_run`, `period.period_number`, `period.tax_year`, `reconciles`,
  and `estimate.amount_gbp` — is computed in Python. Structurally enforced: `_ModelExtract`
  has no field for `reconciles` or `tax_year`, so there is nothing for the model to
  calculate into.
- **Item 7 — PASS.** Grepped the **production** bundle (`.next/static`, `.next/server`,
  `.next/build`), not source: **zero** occurrences of `12570`, `50270`, `125140`, `37700`,
  `PERSONAL_ALLOWANCE`, `BASIC_RATE`, `TaxRegion`, `SCOTLAND`, `getUserFinancials` in any
  first-party asset. The previous report's F8 (a rival Scottish tax engine in `lib/Api.ts`)
  is gone — `Api.ts` is now 60 lines that only `fetch`. *Note:* hits do appear under
  `.next/dev/` — stale dev-server chunks from an earlier build, not served in production.
  Run a clean build before deploying.
- **Item 8 — PASS.** Five full end-to-end runs through the live server with real model
  calls: estimate `419.00`, score `100 (4/4)`, identical finding IDs and an identical
  sorted set of every `£n.nn` string in the response body on all five. Latency 2.90–3.89 s.

### Phase 2 — Rule 2: missing is fine, wrong is not

- **Item 9 — PASS.** All refuse with a typed `UnsupportedPayslip`:
  `S1257L`, `C1257L`, `K475`, `ZZZZ`, `''`, `'  '`, `12X7Q`; and tax years `2025/26`,
  `2019/20`, `2099/00`, `None`, `'garbage'`. Only `2026/27` is accepted.
- **Item 10 — FAIL. See FR-04.** This was the open gap and it is **not** closed.
- **Item 11 — PASS.** `_facts_from_extract()` checks `field in extract.unreadable_fields`
  in addition to `None` for every field it consumes, and refuses (`ValueError`) for
  `period.frequency`, `period.period_number`, `pay.gross_this_period`, `pay.gross_ytd`,
  `deductions.ni_category`, `deductions.student_loan_plan`.
- **Item 12 — PASS.** `extract_payslip` nulls every unreadable path via a generic loop
  (`for dotted_path in unreadable: _null_dotted(...)`) before constructing the
  `PayslipExtract`, and computes `reconciles` from the pre-nulling values first.

### Phase 2 — Rule 3: privacy

- **Item 13 — PASS.** Built a synthetic payslip carrying 15 PII values and **intercepted
  the actual argument passed to `_call_model`** (`verify/final_privacy_payload.py`).
  **All 15 absent**: labelled name, titled inline name, address line, postcode, NI number
  spaced / unspaced / period-separated / lowercase (all with valid prefixes), sort code with
  spaces / dashes / slashes, account number, employee number, email, phone. Separately
  confirmed the NI pattern also catches hyphenated, mixed-separator, and **line-break-split**
  forms. The previous report's F6 is fixed.
- **Item 14 — PASS.** All four date formats survive **intact**: `28/08/2026`, `31-07-2026`,
  `5/8/26`, `2026-08-28` — including the specific regression case, a date adjacent to an
  account number on the same line, which redacts to `Account [BANK] paid 31-07-2026`.
- **Item 15 — PASS.** The gate fails closed: a refusing payload produced **0** model calls,
  and `assert_safe_to_send` sits three lines above the only `_call_model` call. All three
  `RedactionFailure` messages carry a fixed label only, never matched text. The allowlist is
  genuinely independent — `financial_lines_only()` references **none** of the 11 redaction
  regexes and decides purely by positive financial shape (currency / percent / date /
  tax-code / known label). End-to-end over HTTP a gate refusal returns `422` with
  *"We couldn't safely process this document…"*.
- **Item 16 — PASS.** `extract_payslip(pdf_bytes, filename=None)` has no user-context
  parameter. `analysis.py`, `findings.py` and `calculations.py` contain **zero** references
  to `anthropic`, `openai`, `_call_model`, `requests`, `httpx` or `urllib`. `UserContext`
  reaches only `analyse_payslip`, which makes no network call of any kind.
- **Item 17 — PASS.** Audited **every** logging call on the path. All 15 in `main.py` are
  timing plus a fixed string or `type(exc).__name__`. The one that logs an exception
  (`main.py:275`, the gate refusal) is safe — verified all three raise sites emit a fixed
  label. The single `extraction.py` log is a fixed string. The only `print()` is behind
  `if __name__ == "__main__"`. No filesystem or DB write exists anywhere on the path; the
  only `open(` is `pdfplumber.open(io.BytesIO(...))`. `main.py` additionally patches
  `MultiPartParser.spool_max_size` so multipart never spills to a temp file.
- **Item 18 — PASS.** No credential in git history (`git log --all -- .env` empty;
  full-history regex scan for `sk-*` empty). `.gitignore` covers `.env` / `.env.*` with
  `!.env.example`. No secret **value** and no secret **name** (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `SLYP_*`) appears in any built asset.

### Phase 3 — regression against this week's fixes

| # | Item | Result |
|---|------|--------|
| 19 | Expected net accounts for pension and `other`; `None` unless `reconciles is True`; `expected_pension` always `None` | **PASS** — `verify/final_netpay_check.py` cases C/D/E/F: `reconciles=False` → None, `reconciles=None` → None, pension unreadable → None, `other` correctly subtracted |
| 20 | `_check_net_pay` false-mismatch paths | **PASS on guards, FAIL on redundancy** — all four guards hold and are covered; see **FR-07** |
| 21 | Allowlist coverage | **PASS** (2 cosmetic gaps, **FR-15**) — verified 20 label lines carrying no currency; frequency/pay type/pay basis, tax period/month/week, period number, NI category/table/table letter, postgraduate loan/PGL, and every dated pay-date/pay-day/payment-date variant all survive. Negative controls (bare name, bare address, `Deductions`, `Payments`) correctly dropped |
| 22 | Period number | **PASS** — derived always wins (10 boundary dates incl. 6 Apr, 5 Apr, day-5/day-6); `None` when either input missing; label fallback bounded by `_period_number_plausible` (13/monthly, 54/weekly, unknown frequency all rejected); `infer_frequency_from_label` correctly returns `None` for `Period 9`, `Week Ending <date>`, `Fortnightly`, `4-Weekly` |
| 23 | `income_tax_due()` is the single entry point | **PASS** — zero non-test callers of `cumulative_income_tax_due`, `non_cumulative_income_tax_due` or `annual_income_tax` anywhere outside `calculations.py`. *This is also what makes FR-04 bite:* the only function with the £100k refusal is the one nothing calls |
| 24 | Emergency-code estimate | **PASS** — three distinct branches on `only_job` True/False/None; the conditional label reads "if this has been your only **employment this tax year**" (the tax year, not the moment); the previous-employer limitation is documented in `_emergency_basis_finding`'s docstring **and** pinned by `test_emergency_basis_estimate_assumes_no_previous_employer_this_year` |
| 25 | Score | **PASS** — `Score.value` is `None` (not 0) when `checks_run == 0`; a vacuous comparison goes to `not_applicable`, not `checks_passed`; reasons are returned by the API and rendered by `WhatWeChecked`. Live: BR fixture 3/3 with the NI reason; under-threshold fixture 2/2 with two reasons |
| 26 | Tax-year guard | **PASS** — `SUPPORTED_TAX_YEARS = frozenset({TAX_YEAR})`, enforced unconditionally, `None` refuses. Repo-wide grep for `bypass`, `allow_unsupported`, `SLYP_(ALLOW|SKIP|DISABLE|FORCE)`, `override` finds **no flag, env var or constant** that could re-enable it |
| 27 | `payrollMessage.ts` | **PASS** (one latent issue, **FR-11**) — 9/10 tests. Verified against four **real** API responses: carries `£419.00` with the unconditional label when `only_job=true` and with the "if this has been your only employment this tax year" label when unanswered; carries **no** estimate for BR second job; drops every gated and every null clause with no `undefined`, no `£null`, no `NaN`, and no dangling `label:` fragment |

### Phase 4 — outstanding items

| # | Item | Status |
|---|------|--------|
| 28 | Stored-result schema versioning | **DONE.** `RESULT_SCHEMA_VERSION = 1`; anything without that exact version — including every unversioned payload from earlier builds — is discarded on the missing key alone, without inspecting the body, and removed from localStorage. The page shows a `discarded` state rather than an empty one. 7 tests pin it, including "the version check does not inspect the body to decide" |
| 29 | The 400-then-200 | **DONE.** Across **24** `/analyse` requests in one server lifetime there was exactly **one** OpenAI 400 and one retry log line. The cause is documented and real: `gpt-5.6-sol` rejects function tools unless `reasoning_effort` is explicitly `'none'` — a parameter the code never sent. **Both round trips carry the identical, already-gated payload** — proven by forcing the retry and capturing both request bodies: the gate ran once, both requests equalled the gate-approved string, and no second payload was ever constructed. *Caveat:* the flag is per-process, so the first upload after any restart still costs ~1.0 s extra (measured) |
| 30 | Dead code | **DONE.** `CalculationComparison`/`compare_with_payslip()` are gone from `calculations.py` and `tools/try_analysis.py` no longer exists. Both survive only inside the committed stale copy at `verify/patched_pkg/` — see **FR-13** |
| 31 | CLEAR findings under "what we found" | **DONE** — split into "What we found" (action/advisory) and "What we confirmed" (clear). The BR second-job fixture now reads *Nothing obvious needs checking → What we confirmed → the BR card*, with no "What we found" heading above it. See **FR-09** |
| 32 | eslint error in `app/page.tsx` | **NOT DONE** — see **FR-08** |

### Phase 5 — fixtures and behaviour

- **Item 33 — PASS, all four, live.** `python verify/run_regression.py` → **5/5** with real
  model calls: emergency M1 mid-year start → **£419.00** (unconditional when `only_job=true`,
  conditional with the tax-year wording when unanswered); emergency M1 level pay → **no
  estimate**; BR £476 second job → `tax_code_br_multiple_jobs`, no estimate, **3 of 3** with
  the NI not-applicable reason; £583.55 under threshold → **2 of 2** with two reasons.
- **Item 34 — PASS, hand-calculated independently:**

  | Step | Working | Result |
  |---|---|---|
  | Tax year | pay date 28/08/2026 ≥ 6 Apr 2026 | 2026/27 |
  | Period | Aug is 4 calendar months after Apr; day 28 ≥ 6 | month **5** |
  | Cumulative allowance to M5 | £12,570 × 5 ÷ 12 | **£5,237.50** |
  | Cumulative taxable YTD | £7,500.00 − £5,237.50 | **£2,262.50** |
  | Tax a cumulative code would have taken (all within the £37,700 basic band) | £2,262.50 × 20% | **£452.50** |
  | Tax the M1 code actually took (from the payslip) | £871.50 | £871.50 |
  | **Overpayment** | £871.50 − £452.50 | **£419.00** ✓ |

  Cross-check that the payslip is internally consistent: M1 monthly allowance
  £12,570 ÷ 12 = £1,047.50; taxable £2,500.00 − £1,047.50 = £1,452.50; × 20% = **£290.50**
  (the figure printed on the payslip); × 3 payments since starting in period 3 = **£871.50** ✓.
  And the level-pay fixture: 5 × £290.50 = £1,452.50 YTD, while the cumulative equivalent on
  £12,500 YTD is (£12,500 − £5,237.50) × 20% = £1,452.50 — difference **zero**, which is
  exactly why that fixture correctly shows no estimate.
- **Item 35 — PASS.** A deliberately non-reconciling payslip over HTTP: `reconciles=false`,
  `payslip_does_not_reconcile` raised at `action` severity, and `expected_net` correctly
  suppressed so no net-pay finding is invented on top. (Score behaviour: **FR-10**.)
- **Item 36 — PASS, all seven, live over HTTP**, every message plain-English with no
  traceback, no library name, no path, no `null`:

  | Case | HTTP | Message |
  |---|---|---|
  | corrupt PDF | 422 | "This file couldn't be read as a PDF. It may be corrupted…" |
  | password-protected | 422 | "This PDF is password-protected. Please remove the password…" |
  | image-only / no text layer | 422 | "We couldn't read any text from this PDF. If it's a scanned image…" |
  | oversized (11 MB) | 413 | "That file is too large. Please upload a PDF under 10 MB." |
  | empty file | 400 | "The uploaded file is empty. Please choose a payslip PDF." |
  | not a PDF (magic bytes) | 400 | "That doesn't look like a PDF. Please upload a payslip PDF." |
  | gate refusal | 422 | "We couldn't safely process this document…" |
  | unsupported tax year | 200 | `status="unsupported"`, "This payslip is from tax year 2025/26, which is not currently supported." |

### Phase 6 — demo robustness

- **Item 37 — PARTIAL.** Cold start could only be measured **locally** (FR-01). Process
  boot to `/health` 200: **2.15 s**. First upload after boot: **4.38 s** vs a 3.36 s warm
  mean — a **+1.03 s** cold penalty, which is the once-per-process OpenAI discovery round
  trip from item 29. **A warm-up ping is worth doing**: hit `/health` *and* push one fixture
  through `/analyse` before you walk on stage, so the first live upload does not pay it.
  Cold start on a hosted platform (container spin-up, possible scale-to-zero) is UNVERIFIED.
- **Item 38 — PASS (local).** End-to-end for the demo fixture: **2.90–3.89 s**, mean
  **3.43 s** over five runs, plus whatever the venue's network adds.
- **Item 39 — PASS.** Backend: two simultaneous uploads of *different* fixtures returned
  correct, independent results with **no cross-contamination** (emergency → £419.00 4/4;
  BR → no estimate 3/3). Two simultaneous uploads of the *same* fixture returned identical
  analyses (bodies differ only in `source.scanned_at`). Frontend: `handleFileChange` early-
  returns on `isUploading`, the input and trigger button are both `disabled={isUploading}`,
  and `isUploading` is deliberately **not** reset on the success path so no click can slip in
  during navigation.
- **Item 40 — PASS (local).** With **no environment variable set by hand**, the production
  build serves `/` and `/upload` at 200 and its baked-in API base (`http://localhost:8000`)
  matches the backend's default port. CORS preflight from `http://localhost:3000` is
  allowed; an unlisted origin is refused. That same baked-in default is exactly FR-02 once
  this is hosted.
- **Item 41 — was FAIL, now PARTIAL.** No source maps are served (0 `.map` files under
  `.next/static`) and no debug output. The fake paywall (**FR-05**) has since been deleted
  and its absence re-verified against a clean rebuild. Prototype navigation chrome is still
  in the shipped build — **FR-19**, left deliberately.
- **Item 42 — PASS.** Three options render in one row as `flex-1` (equal width) buttons with
  `aria-pressed`. "Not sure" is a real selectable answer, and
  `onlyJobFromAnswer("not_sure") → null`, which `Api.ts` turns into **omitting the field**
  (`if (onlyJob !== null)`), never `false`. Pinned by five tests including
  "'not sure' omits the field entirely - never false" and "the three answers map to three
  distinct outcomes".

### Phase 7 — deployment

**Not deployed.** Items 44 and 45 are UNVERIFIED against production. Item 43 done as far
as the repo allows:

| Variable | `slyp`/`main.py` | `.env.example` | `.env` (local) | Deployment config |
|---|---|---|---|---|
| `SLYP_MODEL_PROVIDER` | `extraction.py:789` | ✓ | ✓ `openai` | **none exists** |
| `SLYP_EXTRACTION_MODEL` | `extraction.py:802,807` | ✓ | ✓ `gpt-5.6-sol` | **none exists** |
| `ANTHROPIC_API_KEY` | read by the SDK | ✓ | present but **empty** | **none exists** |
| `OPENAI_API_KEY` | read by the SDK | ✓ | ✓ set | **none exists** |
| `SLYP_CORS_ORIGINS` | `main.py:83` | ✓ | **absent** (defaults) | **none exists** |
| `NEXT_PUBLIC_API_BASE_URL` | `lib/Api.ts:8` | ✓ | **absent** (defaults) | **none exists** |

Names are **consistent** between code and `.env.example` — no mismatch. `BACKEND_HANDOFF.md`
does not exist. The two variables absent from `.env` are the two that silently misbehave
when unset (**FR-03**), and `NEXT_PUBLIC_API_BASE_URL` is additionally build-time-only
(**FR-02**).

CORS, upload size and timeout **were** tested — against a local server, not production:
preflight allows `http://localhost:3000` (`access-control-allow-methods: GET, POST`,
`max-age: 600`) and refuses an unlisted origin with 400 and no allow-origin header; the
10 MB limit is enforced three times over (content-length pre-check, streaming
`max_part_size`, actual byte length).

---

## What I could not verify, and what blocked it

1. **Everything requiring a deployed URL** — cold start after 30+ minutes idle on real
   infrastructure (item 37), CORS/upload-size/timeout against production (item 44), the
   full demo path in a browser against production (item 45), and deployed-commit-equals-HEAD
   (item 5). **Blocker:** nothing is deployed and no deployment configuration exists
   (FR-01). I measured the local equivalents of 37, 38 and 44 and have labelled them as
   local throughout.
2. **Real browser interaction** — actual clicking through the UI, the rendered appearance of
   findings and the score, and a browser's specific behaviour on the oversized-upload early
   413 (FR-16). **Blocker:** no browser-automation tool available. **Compensating evidence:**
   I ran the production build and fetched the served HTML and JS chunks directly, ran the
   full frontend test suite, and exercised `payrollMessage.ts` against four real API
   responses plus gated and nulled variants. That is stronger than a click-through for
   FR-05 and item 7, but it is not a click-through, so I have not claimed one.
3. **Whether the model reads an unfamiliar real payslip correctly.** Every extraction here
   ran against synthetic fixtures whose layout mimics the collapsed two-column form the
   module documents. **Blocker:** the brief forbids real payslips, correctly. The redaction
   pipeline's own documented residual gap — an **untitled, unlabelled** name sharing a line
   with a currency amount or date — is real, is stated in `redact()`'s docstring, and I
   confirmed it is still open. It did not fire on any fixture because all mine carry either
   a label or a courtesy title.
4. **Rates against gov.uk.** Not re-checked; the previous report verified them live and
   nothing in this week's commits touched the constants.

---

## Verdict

**Yes — safe to run live on 28 August, but only as a laptop demo, and only after the
conditions below.** Not safe to deploy as it stands. *(Written when three conditions were
outstanding. Two have since been fixed at your request — the fake paywall (FR-05) and the
£100k taper gap (FR-04). Only the deployment condition remains.)*

The core of this product is genuinely sound, and I want to be precise about that because it
is unusual: the pipeline order is unskippable, the fail-closed gate actually fails closed,
15 out of 15 PII values were absent from the real intercepted model payload while all four
date formats survived intact, five consecutive live runs were byte-identical, and the
£419.00 figure the demo leads with is arithmetically correct — I derived it independently
and it agrees to the penny, as does the level-pay fixture's correct refusal to show any
figure at all. The score no longer counts vacuous checks, the tax-year guard has no
bypass, stored results from older builds are discarded rather than patched up, and the
copy-to-payroll message carries the right conditional label on the right branch. That is a
lot of careful work and it holds up under execution.

**The conditions, in order:**

1. **Do not deploy without rebuilding with `NEXT_PUBLIC_API_BASE_URL` set** (FR-02) **and
   `SLYP_MODEL_PROVIDER` + `SLYP_CORS_ORIGINS` set in the platform config** (FR-03). Both
   fail in the way that is hardest to debug on stage: the server looks healthy and the first
   upload dies. If you are demoing from the laptop, skip this and start both processes
   fifteen minutes early.
2. ~~**Remove the fake paywall** (FR-05).~~ **Done** — deleted and re-verified against a
   clean rebuild. Consider FR-19 (the remaining prototype "← Back / Next →" chrome) while
   you are in there.
3. ~~**Close the £100k gap**~~ (FR-04). **Done** — the guard is on the live path, the dead
   copy is gone, and the £150,000 repro now returns `unsupported` with a message naming the
   taper. "What happens on a big salary?" is now a question you can answer on stage.

Two smaller things worth doing if there is time: warm the server with one real upload before
you present (FR-06 + the ~1 s cold penalty), and suppress the duplicate net-pay finding so
one wrong number does not read as two problems (FR-07).

**On the claim "a missing field is fine, a wrong field is not":** as first written, this
report said I would not make that claim on stage unqualified, because above £100,000 the
engine produced a confident wrong number instead of refusing. **With FR-04 fixed, I would now
make it.** It holds everywhere I can test it, including the case that broke it.

---

## Top three things most likely to break in a live five-minute demo

1. **A misconfigured environment on a machine that isn't the build machine** — most likely
   by a wide margin, because it is the only failure here with no signal before it happens.
   `/health` returns 200, the page loads, and the first upload returns "Something went wrong
   while analysing this payslip." *Smallest change preventing it:* run the actual demo —
   upload a fixture end to end — on the actual demo laptop, at the venue if possible, before
   you present. Failing that, add a startup assertion that the selected provider's API key
   is present, so a bad config refuses to boot.
2. **Conference wifi turns a 3.4 s upload into a 15 s wait**, and the progress sweep holds
   on "Finishing up" while nothing visible happens. The UI is already built for this (the
   comment on `STEP_INTERVAL_MS` says so explicitly) — the risk is you filling the silence.
   *Smallest change:* none in code. Warm the server first (FR-06), and have the sentence you
   will say during the wait already decided.
3. **A judge asks to try their own payslip.** Three ways that goes wrong, all correct
   behaviour that still reads badly live: only `2026/27` is supported, so anything from an
   earlier year is refused outright (**item 26** — no bypass, deliberately); a real payslip
   whose employee name is neither labelled nor titled can carry that name through to the
   model (the pipeline's own documented residual gap, still open); and a layout unlike the
   two-column form this was tuned against may leave fields unreadable, producing "We could
   not complete every calculation". *Smallest change:* none in code — decide in advance
   whether you accept that offer, and if you do, say up front that it is scoped to the
   current tax year. Refusing cleanly is the product working, but only if you frame it that
   way before it happens.

*(The previous #2 — a judge tapping "Insights" into a fake paywall — has been removed from
the build; see FR-05.)*

---

## The three architectural rules: proved, disproved, or untested

**Rule 1 — "Code calculates, AI explains." PROVED.** Traced every numeric value in a live
response to its origin. The model supplies only transcriptions of figures printed on the
document, plus confidence scores that are never rendered as money. Every derived figure —
the score, the checks, the tax year, the period number, `reconciles`, and the £419.00
estimate itself — is computed in Python. This is enforced structurally, not by convention:
`_ModelExtract` has no field for `reconciles` or `tax_year`, `tool_choice` forces the
structured call so there is no free-text path to answer through, and the production frontend
bundle contains no UK tax constant at all.

**Rule 2 — "A missing field is fine, a wrong field is not." DISPROVED as first verified;
PROVED after the FR-04 fix.** Everywhere I could test it, it holds — and it holds well: Scottish, Welsh, K and unparseable codes all refuse
with a typed result; unsupported and undeterminable tax years refuse with no bypass;
`_facts_from_extract` checks `unreadable_fields` and not merely `None`; a period number is
never accepted from the model without a derivation or a bounded, frequency-confirmed printed
label. But above £100,000 the engine did not refuse — it computed with an allowance the taxpayer
does not have and reported the shortfall as a finding with a pound figure attached. One
reachable case is enough to disprove a rule stated in absolute terms.

That case is now closed (**FR-04**): the guard sits on `income_tax_due()`, the single entry
point both bases dispatch through; the dead copy that protected nothing is deleted; and the
£150,000 repro returns `unsupported` with a message naming the taper. A separate call-graph
audit of every other refusal in the engine — Scotland, Wales, K codes, unsupported tax year,
unparseable codes, the redaction gate — found **none** left on a dead path. On the evidence I
have, Rule 2 now holds. The caveat that remains is not about tax: `findings.py` still carries
an unreachable parallel pipeline whose scorer predates this week's fixes, and whose docstring
invites someone to wire it in (see *Stranded-guard audit*).

**Rule 3 — "Nothing personal reaches an external API, and nothing is persisted." PROVED, to
the limit of synthetic fixtures.** I intercepted the exact string passed to the model rather
than testing `redact()` in isolation: 15 out of 15 PII values absent, including every NI
format the brief named and the two that were broken last week. All four date formats
survived, including a date adjacent to an account number on the same line. The gate fails
closed with zero model calls on refusal, and the allowlist is a genuinely independent
positive filter that shares no regex with the redaction layer. Nothing is written to disk:
no file write, no database, no temp file — `main.py` even patches Starlette's multipart
spool so a large upload cannot spill to disk. Every logging call on the request path was
audited individually and carries only timing, a fixed string, or an exception **type** name.
No credential is in git history or in any built asset. The one caveat I will state plainly:
this is proved against fixtures I wrote, and the pipeline documents one honest residual gap
— an untitled, unlabelled name sharing a line with a financial value — which no fixture of
mine triggered and which remains open.

---

## Appendix: proposed diff for FR-04 (not applied)

The only fix I would call one-line-obvious. It puts the guard on the path everything
actually uses, next to the Scotland guard that is already there.

```python
# slyp/calculations.py, in validate_pay_period_facts(), beside the Scotland check

    # Personal Allowance tapers above £100,000 and reaches zero at
    # £125,140. The engine does not model the taper, so an income above
    # the threshold would be computed with an allowance the taxpayer does
    # not have - a confidently wrong figure, which is the one thing this
    # engine must not produce. annual_income_tax() already refuses on
    # exactly this boundary; it is not on the request path, so the same
    # rule has to be enforced here.
    annualised_gross = annualise(
        facts.gross_this_period,
        facts.gross_ytd,
        facts.period_number,
        facts.frequency,
    )
    if annualised_gross > PERSONAL_ALLOWANCE_TAPER_START:
        raise UnsupportedPayslip(
            "Income above £100,000 is outside the MVP because "
            "Personal Allowance tapering is not supported."
        )
```

`analyse_payslip` already turns an `UnsupportedPayslip` from this path into a
`calculation_error`, so the result degrades to structural-only findings plus
"We could not complete every calculation" — no finding, rather than a wrong one.
Worth confirming against `tests/test_calculations.py` before merging, since some
existing tests construct high-gross facts directly.

## Appendix: scratch files produced by this pass

All under `verify/`, none imported by anything in `slyp/`, `lib/` or `app/`:

`final_rule2_checks.py` (items 9, 10) · `final_netpay_check.py` (19, 20) ·
`final_privacy_payload.py` (13, 14, 16) · `final_gate_and_logging.py` (15, 16, 17) ·
`final_allowlist_period.py` (21, 22) · `final_openai_retry.py` (29) ·
`final_number_provenance.py` (6) · `final_error_paths.py` + `final_e2e.py` (8, 35, 36, 38) ·
`final_concurrency.py` (39) · `final_eventloop.py` (FR-06) ·
`final_payroll_message.test.ts` (27) · `_live_results.json` (captured live API responses).
