// import { Types } from './app/web/next-app/node_modules/zod/src/v3/standard-schema';
import { describe, it, expect } from "vitest";
import {
  maxHoursPerMonth,
  distanceToNextBracket,
  multiJobTaxCodeFlags,
  deriveUserFinancials,
  suggestedMonthlySaving,
} from "./lib/Calculations";
import { createManualPayslip } from "./lib/parse-pdf";
import type { Payslip } from "./app/Types/Types";

const basePayslip: Payslip = {
  id: "1",
  jobLabel: "Primary job",
  month: "2026-08",
  hourlyRate: 12.5,
  grossPay: 1800,
  incomeTax: 150,
  nationalInsurance: 90,
  pensionContribution: 54,
  netPay: 1506,
  taxCode: "1257L",
  scannedAt: Date.now(),
};

describe("maxHoursPerMonth", () => {
  it("returns null when hourlyRate is null (salaried)", () => {
    expect(maxHoursPerMonth(null, 0)).toBeNull();
  });

  it("computes headroom against the monthly personal allowance", () => {
    // MONTHLY_ALLOWANCE = 1047.5, no other income => 1047.5 / 12.5 = 83.8
    expect(maxHoursPerMonth(12.5, 0)).toBeCloseTo(83.8, 1);
  });

  it("returns 0, not negative, once other income exceeds the allowance", () => {
    expect(maxHoursPerMonth(12.5, 20000)).toBe(0);
  });
});

describe("distanceToNextBracket", () => {
  it("returns null when far from a boundary", () => {
    expect(distanceToNextBracket(30000)).toBeNull();
  });

  it("flags when within £1000 of the higher-rate threshold", () => {
    expect(distanceToNextBracket(49800)).toBe(470);
  });

  it("returns null at the top band (nothing to move up to)", () => {
    expect(distanceToNextBracket(200000)).toBeNull();
  });
});

describe("multiJobTaxCodeFlags", () => {
  it("returns nothing for a single job", () => {
    expect(multiJobTaxCodeFlags([basePayslip])).toEqual([]);
  });

  it("flags a secondary job not on BR/D0", () => {
    const secondary: Payslip = {
      ...basePayslip,
      id: "2",
      jobLabel: "Bar work",
      grossPay: 400,
      taxCode: "1257L",
    };
    const flags = multiJobTaxCodeFlags([basePayslip, secondary]);
    expect(flags).toHaveLength(1);
    expect(flags[0].message).toContain("Bar work");
  });

  it("does not flag a secondary job correctly on BR", () => {
    const secondary: Payslip = { ...basePayslip, id: "2", grossPay: 400, taxCode: "BR" };
    expect(multiJobTaxCodeFlags([basePayslip, secondary])).toEqual([]);
  });
});

describe("deriveUserFinancials", () => {
  it("returns a zeroed shape for no payslips (empty state must show no fake numbers)", () => {
    const result = deriveUserFinancials([]);
    expect(result.combinedNetThisMonth).toBe(0);
    expect(result.taxCodeFlags).toEqual([]);
  });

  it("only includes the latest month in currentMonthPayslips", () => {
    const older: Payslip = { ...basePayslip, id: "old", month: "2026-07" };
    const result = deriveUserFinancials([older, basePayslip]);
    expect(result.currentMonthPayslips).toEqual([basePayslip]);
  });
});

describe("suggestedMonthlySaving", () => {
  it("divides remaining amount across remaining months", () => {
    expect(suggestedMonthlySaving(1200, 200, 5)).toBe(200);
  });

  it("does not divide by zero", () => {
    expect(suggestedMonthlySaving(1200, 200, 0)).toBe(1000);
  });
});

describe("createManualPayslip", () => {
  it("builds a valid payslip from manual values", () => {
    const payslip = createManualPayslip({
      jobLabel: "Bar work",
      month: "2026-08",
      grossPay: 2200,
      netPay: 1800,
      incomeTax: 220,
      nationalInsurance: 180,
      pensionContribution: 50,
      taxCode: "1257L",
      hourlyRate: 12.5,
    });

    expect(payslip.jobLabel).toBe("Bar work");
    expect(payslip.month).toBe("2026-08");
    expect(payslip.grossPay).toBe(2200);
    expect(payslip.taxCode).toBe("1257L");
    expect(payslip.netPay).toBe(1800);
  });
});