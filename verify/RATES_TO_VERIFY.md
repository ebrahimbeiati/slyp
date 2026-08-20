# RATES to verify against GOV.UK — 2026/27

Every figure the engine depends on, as it currently sits in `slyp/calculations.py` on `main` (`d538c36`). Case is **(a)**: these are the real, live constants that the shipped code runs on — not placeholders substituted for testing. Confirmed by diffing `slyp/calculations.py` against `verify/patched_pkg/slyp/calculations.py`: the only differences are the two import/typo fixes (F2, F4); every numeric constant is identical between the two.

**Provenance flag**, because it matters for how much to trust each row: the module's original docstring (still present as a dead comment at the top of the file) said *"IMPORTANT: take every rate and threshold below from gov.uk for 2026/27. The values currently in RATES are placeholders and are very likely wrong... Replace them and delete this warning."* That warning is gone in the live version, and there was no commit, comment, or citation showing anyone had done the replacement-and-check step it asked for — hence this file. **All three sections below (income tax, NI, student loans) are now independently confirmed against real GOV.UK/HMRC sources.** Every figure the calculation engine actually uses checks out exactly.

Tick column is for you.

## Income tax — CONFIRMED 2026-08-21

Verified against https://www.gov.uk/income-tax-rates (printed 21/08/2026, current tax year stated as "6 April 2026 to 5 April 2027" — i.e. 2026/27, matching the code's claim). Every figure below matches exactly.

| Rate/threshold | Value in code | Tax year claimed | Source (`slyp/calculations.py`) | ✓ |
|---|---|---|---|---|
| Personal Allowance | £12,570 | 2026/27 | `PERSONAL_ALLOWANCE` (line 403) | ✅ |
| Personal Allowance taper start | £100,000 | 2026/27 | `PERSONAL_ALLOWANCE_TAPER_START` (line 415) | ✅ |
| Basic rate band width (above allowance) | £37,700 | 2026/27 | `BASIC_RATE_LIMIT` (line 406) | ✅ |
| Higher rate threshold (allowance + basic band) | £50,270 | 2026/27 | `HIGHER_RATE_THRESHOLD` (line 409) | ✅ |
| Additional rate threshold | £125,140 | 2026/27 | `ADDITIONAL_RATE_THRESHOLD` (line 412) | ✅ |
| Basic rate | 20% | 2026/27 | `BASIC_RATE` (line 419) | ✅ |
| Higher rate | 40% | 2026/27 | `HIGHER_RATE` (line 420) | ✅ |
| Additional rate | 45% | 2026/27 | `ADDITIONAL_RATE` (line 421) | ✅ |

Note: Personal Allowance taper (the £1-lost-per-£2-over-£100k rule) is explicitly out of MVP scope — income over £100,000 raises `UnsupportedPayslip` rather than being calculated. `personal_allowance_for_income()` implements the taper formula but no live call site currently uses it above the £100k gate. (Separately: `cumulative_income_tax_due()`, the function actually used for every real payslip, doesn't enforce this £100k gate itself — only the unused `annual_income_tax()` does. Flagged in the session's final report as a real gap, not fixed — out of scope for any phase item.)

## Employee National Insurance (Class 1) — CONFIRMED 2026-08-21

Verified against GOV.UK's "Rates and allowances: National Insurance contributions" (HMRC guidance, updated 6 April 2026), 2026 to 2027 column. Every figure in the MVP's actual scope (category A) matches exactly.

| Rate/threshold | Value in code | Tax year claimed | Source | ✓ |
|---|---|---|---|---|
| Primary threshold, monthly | £1,048 | 2026/27 | `NI_MONTHLY_PRIMARY_THRESHOLD` (line 451) | ✅ |
| Upper earnings limit, monthly | £4,189 | 2026/27 | `NI_MONTHLY_UPPER_EARNINGS_LIMIT` (line 452) | ✅ |
| Primary threshold, weekly | £242 | 2026/27 | `NI_WEEKLY_PRIMARY_THRESHOLD` (line 454) | ✅ |
| Upper earnings limit, weekly | £967 | 2026/27 | `NI_WEEKLY_UPPER_EARNINGS_LIMIT` (line 455) | ✅ |
| Category A main rate (between PT and UEL) | 8% | 2026/27 | `NI_CATEGORY_RATES["A"]` (line 507) | ✅ |
| Category A upper rate (above UEL) | 2% | 2026/27 | `NI_CATEGORY_RATES["A"]` (line 507) | ✅ |

Bonus check: the source also states the Married Women's reduced rate as 1.85% (between PT and UEL) for 2026/27, which matches `NI_CATEGORY_RATES["B"]` exactly — a useful cross-check even though category B isn't in the MVP's stated scope.

Other NI categories are also baked into `NI_CATEGORY_RATES` (lines 505-566) but are not part of the MVP's stated scope (category A only) — C, D, E, F, H, I, J, L, M, N, V, Z all have hardcoded rate pairs with no source comment at all, and the source document doesn't itemise all of them either. Not asking for further verification unless the MVP scope widens.

Not needed by the engine, so not checked: employer-side rates and thresholds (Secondary Threshold, UST, AUST, FUST, IZUST, VUST — all employer-facing), the Lower Earnings Limit (record-keeping only, not a deduction threshold), and Class 2/3/4 (self-employed/voluntary NI — out of scope, this engine only handles employee Class 1 via payroll).

## Student loans — CONFIRMED 2026-08-21

Verified against https://www.gov.uk/repaying-your-student-loan/what-you-pay. Every yearly threshold and rate matches exactly — this fully resolves the Plan 1/2/4 discrepancy originally flagged here against the old placeholder dict. The code was correct; the placeholder (dead comment, never live) was the outdated one.

| Plan | Yearly threshold (GOV.UK) | Code's implied annual (monthly×12 / weekly×52) | Rate | ✓ |
|---|---|---|---|---|
| Plan 1 | £26,900 | £26,900 | 9% | ✅ |
| Plan 2 | £29,385 | £29,385 | 9% | ✅ |
| Plan 4 | £33,795 | £33,795 | 9% | ✅ |
| Plan 5 | £25,000 | £25,000 | 9% | ✅ |
| Postgraduate (PG) | £21,000 | £21,000 | 6% | ✅ |

GOV.UK's page displays whole-pound monthly/weekly figures (e.g. Plan 1: "£2,241") in its plain-English worked examples; the code carries the mathematically exact `annual/12` and `annual/52`, floored to the penny (Plan 1: £2,241.66 / £517.30) — the correct derivation for actual payroll deduction, not a discrepancy. Reproduced all three of GOV.UK's own worked examples exactly through the live `student_loan_due()` function:
- Plan 1, £2,750/month → £45 ✓
- Plan 4, £3,000/month → £16 ✓
- Postgraduate portion of the multi-loan example, £2,500/month → £45 ✓

Source in code: `STUDENT_LOAN_THRESHOLDS_MONTHLY` / `STUDENT_LOAN_THRESHOLDS_WEEKLY` / `STUDENT_LOAN_RATES` (`slyp/calculations.py`).

## Not yet implemented / not applicable

- Scottish income tax bands: not present anywhere in the code (rest-of-UK bands are never applied to a Scottish code — see Phase 3 plan re: refusing `S`/`C` prefixes).
- Welsh income tax: Wales uses the same bands as England/NI in practice (Senedd has kept rates aligned), so `C`-prefixed codes are not a *rates* problem the same way Scotland is — but per the Phase 3 decision, they'll be refused anyway rather than assumed.
