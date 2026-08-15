import type { Payslip } from "@/app/Types/Types";

// Senior Type Architecture Definitions
export type PayFrequency = "WEEKLY" | "FORTNIGHTLY" | "MONTHLY";
export type StudentLoanPlan = "NONE" | "PLAN_1" | "PLAN_2" | "PLAN_4" | "PLAN_5" | "POSTGRAD";
export type TaxRegion = "UK_STANDARD" | "SCOTLAND";

export interface ExtendedPayslip extends Payslip {
  frequency: PayFrequency;
  region: TaxRegion;
  studentLoanPlan: StudentLoanPlan;
}

export interface FinancialSummary {
  combinedNetThisMonth: number;
  combinedGrossThisMonth: number;
  annualGrossProjected: number;
  distanceToNextBracket: number;
  taxCodeFlags: { type: string; message: string }[];
}

/**
 * Professional Calculation Engine calibrated for the 2026/2027 UK tax year boundaries.
 */
export function getUserFinancials(payslips: ExtendedPayslip[]): FinancialSummary {
  let totalNetThisMonth = 0;
  let totalGrossThisMonth = 0;
  let totalAnnualGrossProjected = 0;
  const flags: { type: string; message: string }[] = [];

  if (!payslips || payslips.length === 0) {
    return {
      combinedNetThisMonth: 0,
      combinedGrossThisMonth: 0,
      annualGrossProjected: 0,
      distanceToNextBracket: 50270,
      taxCodeFlags: [],
    };
  }

  // Iterate over each distinct position ledger item to unify base periods
  payslips.forEach((p) => {
    let monthlyGross = p.grossPay;
    let monthlyNet = p.netPay;
    let multiplier = 12;

    if (p.frequency === "WEEKLY") {
      monthlyGross = p.grossPay * 4.333;
      monthlyNet = p.netPay * 4.333;
      multiplier = 52;
    } else if (p.frequency === "FORTNIGHTLY") {
      monthlyGross = p.grossPay * 2.166;
      monthlyNet = p.netPay * 2.166;
      multiplier = 26;
    }

    totalGrossThisMonth += monthlyGross;
    totalNetThisMonth += monthlyNet;
    totalAnnualGrossProjected += p.grossPay * multiplier;

    // Detect Emergency Tax code flags
    const normalizedCode = p.taxCode.toUpperCase();
    if (["BR", "0T", "NT"].includes(normalizedCode) || normalizedCode.endsWith("M1") || normalizedCode.endsWith("W1")) {
      flags.push({
        type: "EMERGENCY_TAX",
        message: `Position "${p.jobLabel}" is utilizing an emergency tax marker (${p.taxCode}). You are missing your Personal Allowance splits here.`,
      });
    }

    // Run structural calculation analysis for Student Loan deductions
    const loanDeduction = calculateStudentLoanDeduction(p.grossPay, p.frequency, p.studentLoanPlan);
    if (loanDeduction > 0) {
      // Flag check warning to ensure deductions align with physical pay slates
      flags.push({
        type: "STUDENT_LOAN_ACTIVE",
        message: `Detected active ${p.studentLoanPlan} tracking metrics. Estimated deduction target: £${loanDeduction} inside this runtime block.`,
      });
    }
  });

  // Calculate bracket targets based on the primary region parameter selection
  const primaryRegion = payslips[0]?.region ?? "UK_STANDARD";
  let distanceToNext = 0;

  if (primaryRegion === "SCOTLAND") {
    // 2026/27 Scottish Higher Threshold steps down to £43,663 vs Rest of UK £50,270
    if (totalAnnualGrossProjected < 43663) {
      distanceToNext = 43663 - totalAnnualGrossProjected;
    } else if (totalAnnualGrossProjected < 75000) {
      distanceToNext = 75000 - totalAnnualGrossProjected;
    }
  } else {
    // Rest of UK (rUK) Higher Threshold remains frozen at £50,270
    if (totalAnnualGrossProjected < 50270) {
      distanceToNext = 50270 - totalAnnualGrossProjected;
    } else if (totalAnnualGrossProjected < 125140) {
      distanceToNext = 125140 - totalAnnualGrossProjected;
    }
  }

  return {
    combinedNetThisMonth: Math.round(totalNetThisMonth),
    combinedGrossThisMonth: Math.round(totalGrossThisMonth),
    annualGrossProjected: Math.round(totalAnnualGrossProjected),
    distanceToNextBracket: Math.max(0, Math.round(distanceToNext)),
    taxCodeFlags: flags,
  };
}

/**
 * Computes exact Student Loan adjustments matching official 2026/2027 statutory tables.
 */
function calculateStudentLoanDeduction(gross: number, freq: PayFrequency, plan: StudentLoanPlan): number {
  if (plan === "NONE") return 0;

  // Set up matching thresholds parameter metrics per period allocation matrices
  const thresholds: Record<StudentLoanPlan, { weekly: number; monthly: number; rate: number }> = {
    NONE: { weekly: 0, monthly: 0, rate: 0 },
    PLAN_1: { weekly: 517.30, monthly: 2241.66, rate: 0.09 },  // £26,900 threshold
    PLAN_2: { weekly: 565.09, monthly: 2448.75, rate: 0.09 },  // £29,385 threshold
    PLAN_4: { weekly: 649.90, monthly: 2816.25, rate: 0.09 },  // £33,795 Scottish threshold
    PLAN_5: { weekly: 480.76, monthly: 2083.33, rate: 0.09 },  // £25,000 threshold (PAYE active)
    POSTGRAD: { weekly: 403.84, monthly: 1750.00, rate: 0.06 }, // £21,000 threshold
  };

  const config = thresholds[plan];
  const threshold = freq === "WEEKLY" ? config.weekly : freq === "FORTNIGHTLY" ? config.weekly * 2 : config.monthly;

  if (gross <= threshold) return 0;
  
  // UK Rule: Deduct threshold, multiply excess by percentage, round down to whole pound
  return Math.floor((gross - threshold) * config.rate);
}
/**
 * Simulated backend parsing function to fulfill compilation constraints cleanly.
 * Delays processing for prototype realism and safely converts files to mock objects.
 */
export async function parsePayslip(file: File, jobLabel: string): Promise<{
  success: boolean;
  payslip?: unknown;
  missingFields: string[];
}> {
  // Simulate network extraction processing time delay latency
  await new Promise((resolve) => setTimeout(resolve, 1500));

  // If a file is successfully attached, hand back a valid schema layout target structure
  if (file) {
    return {
      success: true,
      missingFields: [],
      payslip: {
        id: `ocr_sim_${Date.now()}`,
        jobLabel: jobLabel || "Primary job",
        month: new Date().toISOString().slice(0, 7),
        grossPay: 2523,
        netPay: 1842,
        incomeTax: 535,
        nationalInsurance: 146,
        taxCode: "1257L",
        frequency: "MONTHLY",
        region: "UK_STANDARD",
        studentLoanPlan: "NONE"
      }
    };
  }

  return {
    success: false,
    missingFields: ["grossPay", "netPay", "taxCode"]
  };
}
