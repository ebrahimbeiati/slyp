// Data model — build spec §1.
// Everything on screen derives from these. If a screen needs a field
// that isn't here, add it here first, not as a one-off prop.

export type Payslip = {
  id: string;
  jobLabel: string; // "Primary job", "Bar work"
  month: string; // "2026-08"
  hourlyRate: number | null; // extracted from payslip, or null if salaried
  grossPay: number;
  incomeTax: number;
  nationalInsurance: number;
  pensionContribution: number;
  netPay: number;
  taxCode: string; // "1257L", "BR", "D0", "0T", etc.
  scannedAt: number; // epoch ms
};

export type FlagType = "bracket_distance" | "multi_job_tax_code";

export type Flag = {
  type: FlagType;
  severity: "info" | "warn";
  message: string; // always hedged copy — "possible issue", "worth checking"
};

// Derived per user, recomputed whenever a payslip is added. Never store
// this — always recompute from Payslip[] via deriveUserFinancials().
export type UserFinancials = {
  payslips: Payslip[];
  currentMonthPayslips: Payslip[];
  combinedNetThisMonth: number;
  combinedGrossThisMonth: number;
  annualGrossProjected: number;
  distanceToNextBracket: number | null; // null when not close to a boundary
  taxCodeFlags: Flag[];
};

export type SavingsGoal = {
  name: string;
  targetAmount: number;
  targetMonths: number;
  savedSoFar: number;
  suggestedMonthly: number;
};

// What the PDF parser (or the manual-entry fallback) hands back.
// success === false means "show the manual entry form", not an error page.
export type ParseResult = {
  success: boolean;
  payslip: Payslip | null;
  missingFields: (keyof Payslip)[];
  confidence: "high" | "low";
};