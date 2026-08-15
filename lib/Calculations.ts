import type { Payslip, UserFinancials, Flag, SavingsGoal } from "../app/Types/Types";

// ---------------------------------------------------------------------------
// Constants — 2026/27 UK tax year. Update these in one place each tax year;
// nothing else in the app should hardcode a band or allowance number.
// ---------------------------------------------------------------------------

export const PERSONAL_ALLOWANCE_ANNUAL = 12570;
export const MONTHLY_ALLOWANCE = PERSONAL_ALLOWANCE_ANNUAL / 12; // £1,047.50

export const BANDS_2026_27 = [
  { upTo: 12570, rate: 0 },
  { upTo: 50270, rate: 0.2 },
  { upTo: 125140, rate: 0.4 },
  { upTo: Infinity, rate: 0.45 },
] as const;

// Below this gap to the next threshold, the bracket flag is worth showing.
// Above it, it's noise on every dashboard — build spec §3.
const BRACKET_FLAG_THRESHOLD = 1000;

// ---------------------------------------------------------------------------
// Part-time / "extra hours" calculator — the feature the pitch is built on.
// Get this one exactly right; it's covered by the unit tests below.
// ---------------------------------------------------------------------------

/**
 * Tax-free hours remaining this month before the user starts paying income
 * tax on additional earnings, given their hourly rate.
 *
 * Returns null when hourlyRate is null/0 — the UI must not render the
 * part-time calculator in that case (spec §2, item 7).
 */
export function maxHoursPerMonth(
  hourlyRate: number | null,
  otherTaxableIncomeThisYear: number
): number | null {
  if (!hourlyRate || hourlyRate <= 0) return null;
  const headroom = MONTHLY_ALLOWANCE - otherTaxableIncomeThisYear / 12;
  if (headroom <= 0) return 0;
  return headroom / hourlyRate;
}

// ---------------------------------------------------------------------------
// Distance to next tax bracket
// ---------------------------------------------------------------------------

export function distanceToNextBracket(annualGrossProjected: number): number | null {
  const nextBand = BANDS_2026_27.find((b) => annualGrossProjected < b.upTo);
  if (!nextBand || nextBand.upTo === Infinity) return null;
  const distance = nextBand.upTo - annualGrossProjected;
  return distance < BRACKET_FLAG_THRESHOLD ? distance : null;
}

// ---------------------------------------------------------------------------
// Multi-job tax code flag — heuristic, not a certainty. Copy must stay
// hedged ("possible issue" / "worth checking") per spec §3 — do not tighten
// this into a definitive diagnosis anywhere downstream.
// ---------------------------------------------------------------------------

export function multiJobTaxCodeFlags(currentMonthPayslips: Payslip[]): Flag[] {
  if (currentMonthPayslips.length <= 1) return [];

  // Primary job = highest gross pay this month, by convention.
  const primary = currentMonthPayslips.reduce((a, b) => (a.grossPay >= b.grossPay ? a : b));
  const secondaryJobs = currentMonthPayslips.filter((p) => p.id !== primary.id);

  const flags: Flag[] = [];
  for (const job of secondaryJobs) {
    if (job.taxCode !== "BR" && job.taxCode !== "D0") {
      flags.push({
        type: "multi_job_tax_code",
        severity: "warn",
        message: `${job.jobLabel}'s tax code is ${job.taxCode} — second jobs are usually BR. Possible issue, worth checking with HMRC.`,
      });
    }
  }
  return flags;
}

// ---------------------------------------------------------------------------
// Roll-up: everything the dashboard needs, recomputed from raw payslips.
// Never persist the output of this function — always derive it fresh.
// ---------------------------------------------------------------------------

export function deriveUserFinancials(payslips: Payslip[]): UserFinancials {
  if (payslips.length === 0) {
    return {
      payslips: [],
      currentMonthPayslips: [],
      combinedNetThisMonth: 0,
      combinedGrossThisMonth: 0,
      annualGrossProjected: 0,
      distanceToNextBracket: null,
      taxCodeFlags: [],
    };
  }

  const latestMonth = payslips.reduce((latest, p) => (p.month > latest ? p.month : latest), payslips[0].month);
  const currentMonthPayslips = payslips.filter((p) => p.month === latestMonth);

  const combinedNetThisMonth = sum(currentMonthPayslips.map((p) => p.netPay));
  const combinedGrossThisMonth = sum(currentMonthPayslips.map((p) => p.grossPay));

  // Naive annualisation — spec §1 flags this explicitly as naive (no
  // seasonality, no allowance for mid-year rate changes). Fine for MVP.
  const annualGrossProjected = combinedGrossThisMonth * 12;

  const bracketDistance = distanceToNextBracket(annualGrossProjected);
  const taxCodeFlags = multiJobTaxCodeFlags(currentMonthPayslips);

  return {
    payslips,
    currentMonthPayslips,
    combinedNetThisMonth,
    combinedGrossThisMonth,
    annualGrossProjected,
    distanceToNextBracket: bracketDistance,
    taxCodeFlags,
  };
}

// ---------------------------------------------------------------------------
// Scenario calculator — "what if I work N extra hours this month"
// ---------------------------------------------------------------------------

export type ScenarioResult = {
  baseline: { gross: number; tax: number; ni: number; net: number };
  scenario: { gross: number; tax: number; ni: number; net: number };
  delta: { gross: number; net: number };
};

/**
 * Estimates the effect of extra hours on gross/tax/NI/net for one job.
 * This is a simplification (flat marginal rate at the job's current band,
 * NI treated as a flat rate above the primary threshold) — sufficient for
 * an in-app estimate, not a payroll-grade calculation. Say so in the UI copy.
 */
export function calculateExtraHoursScenario(
  payslip: Payslip,
  extraHours: number,
  annualGrossProjected: number
): ScenarioResult | null {
  if (!payslip.hourlyRate || payslip.hourlyRate <= 0) return null;

  const extraGross = extraHours * payslip.hourlyRate;
  const marginalBand = BANDS_2026_27.find((b) => annualGrossProjected < b.upTo) ?? BANDS_2026_27[BANDS_2026_27.length - 1];
  const marginalTaxRate = marginalBand.rate;

  // Flat 8% employee NI above primary threshold — an approximation for
  // in-app estimates, not the tiered real calculation. Flag as such in copy.
  const marginalNiRate = annualGrossProjected > 12570 ? 0.08 : 0;

  const extraTax = extraGross * marginalTaxRate;
  const extraNi = extraGross * marginalNiRate;
  const extraNet = extraGross - extraTax - extraNi;

  return {
    baseline: {
      gross: payslip.grossPay,
      tax: payslip.incomeTax,
      ni: payslip.nationalInsurance,
      net: payslip.netPay,
    },
    scenario: {
      gross: payslip.grossPay + extraGross,
      tax: payslip.incomeTax + extraTax,
      ni: payslip.nationalInsurance + extraNi,
      net: payslip.netPay + extraNet,
    },
    delta: {
      gross: extraGross,
      net: extraNet,
    },
  };
}

// ---------------------------------------------------------------------------
// Savings goal
// ---------------------------------------------------------------------------

export function suggestedMonthlySaving(
  targetAmount: number,
  savedSoFar: number,
  monthsRemaining: number
): number {
  if (monthsRemaining <= 0) return Math.max(targetAmount - savedSoFar, 0);
  return (targetAmount - savedSoFar) / monthsRemaining;
}

export function buildSavingsGoal(
  name: string,
  targetAmount: number,
  targetMonths: number,
  savedSoFar: number
): SavingsGoal {
  return {
    name,
    targetAmount,
    targetMonths,
    savedSoFar,
    suggestedMonthly: suggestedMonthlySaving(targetAmount, savedSoFar, targetMonths),
  };
}

// ---------------------------------------------------------------------------
function sum(values: number[]): number {
  return values.reduce((a, b) => a + b, 0);
}