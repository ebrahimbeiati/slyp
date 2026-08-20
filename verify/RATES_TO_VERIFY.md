# RATES to verify against GOV.UK — 2026/27

Every figure the engine depends on, as it currently sits in `slyp/calculations.py` on `main` (`d538c36`). Case is **(a)**: these are the real, live constants that the shipped code runs on — not placeholders substituted for testing. Confirmed by diffing `slyp/calculations.py` against `verify/patched_pkg/slyp/calculations.py`: the only differences are the two import/typo fixes (F2, F4); every numeric constant is identical between the two.

**Provenance flag**, because it matters for how much to trust each row: the module's original docstring (still present as a dead comment at the top of the file) said *"IMPORTANT: take every rate and threshold below from gov.uk for 2026/27. The values currently in RATES are placeholders and are very likely wrong... Replace them and delete this warning."* That warning is gone in the live version, but there is no commit, comment, or citation showing anyone actually did the replacement-and-check step it asked for. Income tax and NI figures below are numerically identical to the old placeholder dict (still visible as a comment, `slyp/calculations.py:43-73`) — so either the placeholder was already correct, or nobody touched it. The three student loan figures marked below are **not** identical to the placeholder and have no citation for either the old or the new number.

Tick column is for you.

## Income tax

| Rate/threshold | Value in code | Tax year claimed | Source (`slyp/calculations.py`) | ✓ |
|---|---|---|---|---|
| Personal Allowance | £12,570 | 2026/27 | `PERSONAL_ALLOWANCE` (line 403) | ☐ |
| Personal Allowance taper start | £100,000 | 2026/27 | `PERSONAL_ALLOWANCE_TAPER_START` (line 415) | ☐ |
| Basic rate band width (above allowance) | £37,700 | 2026/27 | `BASIC_RATE_LIMIT` (line 406) | ☐ |
| Higher rate threshold (allowance + basic band) | £50,270 | 2026/27 | `HIGHER_RATE_THRESHOLD` (line 409) | ☐ |
| Additional rate threshold | £125,140 | 2026/27 | `ADDITIONAL_RATE_THRESHOLD` (line 412) | ☐ |
| Basic rate | 20% | 2026/27 | `BASIC_RATE` (line 419) | ☐ |
| Higher rate | 40% | 2026/27 | `HIGHER_RATE` (line 420) | ☐ |
| Additional rate | 45% | 2026/27 | `ADDITIONAL_RATE` (line 421) | ☐ |

Note: Personal Allowance taper (the £1-lost-per-£2-over-£100k rule) is explicitly out of MVP scope — income over £100,000 raises `UnsupportedPayslip` rather than being calculated. `personal_allowance_for_income()` implements the taper formula but no live call site currently uses it above the £100k gate.

## Employee National Insurance (Class 1)

| Rate/threshold | Value in code | Tax year claimed | Source | ✓ |
|---|---|---|---|---|
| Primary threshold, monthly | £1,048 | 2026/27 | `NI_MONTHLY_PRIMARY_THRESHOLD` (line 451) | ☐ |
| Upper earnings limit, monthly | £4,189 | 2026/27 | `NI_MONTHLY_UPPER_EARNINGS_LIMIT` (line 452) | ☐ |
| Primary threshold, weekly | £242 | 2026/27 | `NI_WEEKLY_PRIMARY_THRESHOLD` (line 454) | ☐ |
| Upper earnings limit, weekly | £967 | 2026/27 | `NI_WEEKLY_UPPER_EARNINGS_LIMIT` (line 455) | ☐ |
| Category A main rate (between PT and UEL) | 8% | 2026/27 | `NI_CATEGORY_RATES["A"]` (line 507) | ☐ |
| Category A upper rate (above UEL) | 2% | 2026/27 | `NI_CATEGORY_RATES["A"]` (line 507) | ☐ |

Other NI categories are also baked into `NI_CATEGORY_RATES` (lines 505-566) but are not part of the MVP's stated scope (category A only) — B, C, D, E, F, H, I, J, L, M, N, V, Z all have hardcoded rate pairs with no source comment at all. Flagging for awareness; not asking you to verify all 13 unless the MVP scope has widened.

## Student loans

| Plan | Monthly threshold in code | Weekly threshold in code | Implied annual threshold | Rate | Old placeholder annual (dead comment, line 67-71) | Matches? | ✓ |
|---|---|---|---|---|---|---|---|
| Plan 1 | £2,241.66 | £517.30 | ≈ £26,900 | 9% | £26,065 | **✗ different** | ☐ |
| Plan 2 | £2,448.75 | £565.09 | £29,385 | 9% | £28,470 | **✗ different** | ☐ |
| Plan 4 | £2,816.25 | £649.90 | £33,795 | 9% | £32,745 | **✗ different** | ☐ |
| Plan 5 | £2,083.33 | £480.76 | £25,000 | 9% | £25,000 | ✓ same | ☐ |
| Postgraduate (PG) | £1,750.00 | £403.84 | £21,000 | 6% | £21,000 | ✓ same | ☐ |

**Flagging Plan 1, 2, and 4 specifically** — these three don't match the old placeholder dict and have no citation for the new number either. I have not corrected these; I don't have a source to cite. Please check these three against gov.uk/repaying-your-student-loan/what-you-pay before the demo — they're the ones most likely to be either a genuine 2026/27 uprating (plausible, thresholds move most years) or an uncredited guess.

Source in code: `STUDENT_LOAN_THRESHOLDS_MONTHLY` / `STUDENT_LOAN_THRESHOLDS_WEEKLY` / `STUDENT_LOAN_RATES` (`slyp/calculations.py:465-487`).

## Not yet implemented / not applicable

- Scottish income tax bands: not present anywhere in the code (rest-of-UK bands are never applied to a Scottish code — see Phase 3 plan re: refusing `S`/`C` prefixes).
- Welsh income tax: Wales uses the same bands as England/NI in practice (Senedd has kept rates aligned), so `C`-prefixed codes are not a *rates* problem the same way Scotland is — but per the Phase 3 decision, they'll be refused anyway rather than assumed.
