import type { Payslip } from "@/app/Types/Types";
import {
  parsePayslipPdf,
  createManualPayslip,
  type ManualPayslipInput,
} from "@/lib/parse-pdf";

// ============================================================================
// Types
// ============================================================================

export type PayFrequency =
  | "WEEKLY"
  | "FORTNIGHTLY"
  | "MONTHLY";

export type StudentLoanPlan =
  | "NONE"
  | "PLAN_1"
  | "PLAN_2"
  | "PLAN_4"
  | "PLAN_5"
  | "POSTGRAD";

export type TaxRegion =
  | "UK_STANDARD"
  | "SCOTLAND";

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
  taxCodeFlags: {
    type: string;
    message: string;
  }[];
}

export async function parsePayslip(
  file: File,
  jobLabel = "Primary job",
) {
  if (!(file instanceof File)) {
    return {
      success: false,
      payslip: null,
      missingFields: [
        "grossPay",
        "incomeTax",
        "nationalInsurance",
        "netPay",
        "taxCode",
      ] as (keyof Payslip)[],
      confidence: "low" as const,
    };
  }

  if (file.type !== "application/pdf") {
    return {
      success: false,
      payslip: null,
      missingFields: [
        "grossPay",
        "incomeTax",
        "nationalInsurance",
        "netPay",
        "taxCode",
      ] as (keyof Payslip)[],
      confidence: "low" as const,
    };
  }

  return parsePayslipPdf(file, jobLabel);
}

// ============================================================================
// Manual entry
// ============================================================================

export function createPayslipFromManualEntry(
  input: ManualPayslipInput,
): Payslip {
  return createManualPayslip(input);
}

// ============================================================================
// Financial calculations
// ============================================================================


export function getUserFinancials(
  payslips: ExtendedPayslip[],
): FinancialSummary {
  if (!payslips || payslips.length === 0) {
    return {
      combinedNetThisMonth: 0,
      combinedGrossThisMonth: 0,
      annualGrossProjected: 0,
      distanceToNextBracket: 50270,
      taxCodeFlags: [],
    };
  }

  let totalNetThisMonth = 0;
  let totalGrossThisMonth = 0;
  let totalAnnualGrossProjected = 0;

  const flags: {
    type: string;
    message: string;
  }[] = [];

  for (const payslip of payslips) {
    const {
      grossPay,
      netPay,
      taxCode,
      frequency,
      jobLabel,
      studentLoanPlan,
    } = payslip;

    // ------------------------------------------------------------
    // Convert the current pay period into monthly equivalent.
    // ------------------------------------------------------------

    let monthlyGross = grossPay;
    let monthlyNet = netPay;

    let annualMultiplier = 12;

    switch (frequency) {
      case "WEEKLY":
        monthlyGross = grossPay * (52 / 12);
        monthlyNet = netPay * (52 / 12);
        annualMultiplier = 52;
        break;

      case "FORTNIGHTLY":
        monthlyGross = grossPay * (26 / 12);
        monthlyNet = netPay * (26 / 12);
        annualMultiplier = 26;
        break;

      case "MONTHLY":
      default:
        monthlyGross = grossPay;
        monthlyNet = netPay;
        annualMultiplier = 12;
        break;
    }

    totalGrossThisMonth += monthlyGross;
    totalNetThisMonth += monthlyNet;

    totalAnnualGrossProjected +=
      grossPay * annualMultiplier;

    // ------------------------------------------------------------
    // Tax-code checks
    // ------------------------------------------------------------

    const normalizedCode = taxCode
      .trim()
      .toUpperCase()
      .replace(/\s+/g, "");

    const emergencyTax =
      normalizedCode.endsWith("M1") ||
      normalizedCode.endsWith("W1") ||
      normalizedCode.endsWith("X");

    if (emergencyTax) {
      flags.push({
        type: "EMERGENCY_TAX",
        message:
          `Position "${jobLabel}" is using tax code ` +
          `${taxCode}, which appears to be on an ` +
          `emergency/non-cumulative basis. It is worth checking ` +
          `with HMRC or payroll.`,
      });
    }

    if (
      normalizedCode === "BR" ||
      normalizedCode === "D0" ||
      normalizedCode === "D1" ||
      normalizedCode === "0T"
    ) {
      flags.push({
        type: "MULTI_JOB_TAX_CODE",
        message:
          `Position "${jobLabel}" is using tax code ${taxCode}. ` +
          `This can be correct when your Personal Allowance is ` +
          `being used elsewhere, but it is worth checking if this ` +
          `is your only job.`,
      });
    }

    // ------------------------------------------------------------
    // Student loan
    // ------------------------------------------------------------

    if (studentLoanPlan && studentLoanPlan !== "NONE") {
      const estimatedDeduction =
        calculateStudentLoanDeduction(
          grossPay,
          frequency,
          studentLoanPlan,
        );

      if (estimatedDeduction > 0) {
        flags.push({
          type: "STUDENT_LOAN_ACTIVE",
          message:
            `A ${studentLoanPlan.replace("_", " ")} student ` +
            `loan deduction may apply to "${jobLabel}". ` +
            `Estimated deduction for this pay period: ` +
            `£${estimatedDeduction.toFixed(2)}.`,
        });
      }
    }
  }

  // ------------------------------------------------------------
  // Next tax bracket
  // ------------------------------------------------------------

  const primaryRegion =
    payslips[0]?.region ?? "UK_STANDARD";

  let nextBracket = 0;

  if (primaryRegion === "SCOTLAND") {
    if (totalAnnualGrossProjected < 43663) {
      nextBracket =
        43663 - totalAnnualGrossProjected;
    } else if (totalAnnualGrossProjected < 75000) {
      nextBracket =
        75000 - totalAnnualGrossProjected;
    }
  } else {
    if (totalAnnualGrossProjected < 50270) {
      nextBracket =
        50270 - totalAnnualGrossProjected;
    } else if (totalAnnualGrossProjected < 125140) {
      nextBracket =
        125140 - totalAnnualGrossProjected;
    }
  }

  return {
    combinedNetThisMonth: roundMoney(
      totalNetThisMonth,
    ),

    combinedGrossThisMonth: roundMoney(
      totalGrossThisMonth,
    ),

    annualGrossProjected: roundMoney(
      totalAnnualGrossProjected,
    ),

    distanceToNextBracket: Math.max(
      0,
      roundMoney(nextBracket),
    ),

    taxCodeFlags: flags,
  };
}

// ============================================================================
// Student loan calculation
// ============================================================================

function calculateStudentLoanDeduction(
  gross: number,
  frequency: PayFrequency,
  plan: StudentLoanPlan,
): number {
  if (plan === "NONE") {
    return 0;
  }

  const thresholds: Record<
    StudentLoanPlan,
    {
      weekly: number;
      monthly: number;
      rate: number;
    }
  > = {
    NONE: {
      weekly: 0,
      monthly: 0,
      rate: 0,
    },

    PLAN_1: {
      weekly: 517.30,
      monthly: 2241.66,
      rate: 0.09,
    },

    PLAN_2: {
      weekly: 565.09,
      monthly: 2448.75,
      rate: 0.09,
    },

    PLAN_4: {
      weekly: 649.90,
      monthly: 2816.25,
      rate: 0.09,
    },

    PLAN_5: {
      weekly: 480.76,
      monthly: 2083.33,
      rate: 0.09,
    },

    POSTGRAD: {
      weekly: 403.84,
      monthly: 1750.00,
      rate: 0.06,
    },
  };

  const config = thresholds[plan];

  let threshold: number;

  switch (frequency) {
    case "WEEKLY":
      threshold = config.weekly;
      break;

    case "FORTNIGHTLY":
      threshold = config.weekly * 2;
      break;

    case "MONTHLY":
    default:
      threshold = config.monthly;
      break;
  }

  if (gross <= threshold) {
    return 0;
  }

  return Math.floor(
    (gross - threshold) * config.rate,
  );
}

// ============================================================================
// Utility
// ============================================================================

function roundMoney(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}