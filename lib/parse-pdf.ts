import type { Payslip, ParseResult } from "../app/Types/Types";

// ============================================================================
// Types
// ============================================================================

type PdfLine = {
  text: string;
  x: number;
  y: number;
};

type ExtractedValue = {
  value: number;
  source: string;
  confidence: number;
};

type ExtractionResult = {
  grossPay: ExtractedValue | null;
  incomeTax: ExtractedValue | null;
  nationalInsurance: ExtractedValue | null;
  pensionContribution: ExtractedValue | null;
  netPay: ExtractedValue | null;
  taxCode: string | null;
  hourlyRate: ExtractedValue | null;
  hours: ExtractedValue | null;
  payDate: Date | null;
  frequency: "MONTHLY" | "WEEKLY" | null;
};

// ============================================================================
// Public API
// ============================================================================

export type ManualPayslipInput = {
  jobLabel?: string;
  month?: string;
  grossPay: number | string;
  incomeTax: number | string;
  nationalInsurance: number | string;
  pensionContribution?: number | string;
  netPay: number | string;
  taxCode: string;
  hourlyRate?: number | string | null;
};

// ============================================================================
// Money / text helpers
// ============================================================================

function parseMoney(raw: string | undefined | null): number | null {
  if (!raw) return null;

  let value = raw
    .replace(/\u00a0/g, " ")
    .replace(/[£$€]/g, "")
    .replace(/\s/g, "")
    .trim();

  if (!value) return null;

  // Remove thousands separators.
  value = value.replace(/,/g, "");

  // Handle accounting-style negatives: (£123.45)
  if (/^\(.*\)$/.test(value)) {
    value = `-${value.slice(1, -1)}`;
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return null;
  }

  return number;
}

function parseNumber(raw: string | undefined | null): number | null {
  if (!raw) return null;

  const value = raw
    .replace(/\u00a0/g, " ")
    .replace(/,/g, "")
    .trim();

  const number = Number(value);

  return Number.isFinite(number) ? number : null;
}

function normaliseText(value: string): string {
  return value
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .trim();
}

function normaliseForMatching(value: string): string {
  return normaliseText(value)
    .toLowerCase()
    .replace(/[–—]/g, "-");
}

function nearlyEqual(a: number, b: number, tolerance = 0.02): boolean {
  return Math.abs(a - b) <= tolerance;
}

// ============================================================================
// PDF extraction
// ============================================================================


async function extractPdfLines(file: File): Promise<string[]> {
  const pdfjsLib = await import("pdfjs-dist");

  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url,
  ).toString();

  const arrayBuffer = await file.arrayBuffer();

  const pdf = await pdfjsLib.getDocument({
    data: arrayBuffer,
  }).promise;

  const lines: string[] = [];

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();

    const positionedItems: PdfLine[] = [];

    for (const item of content.items) {
      if (!("str" in item)) {
        continue;
      }

      const text = normaliseText(item.str);

      if (!text) {
        continue;
      }

      const transform = "transform" in item ? item.transform : undefined;

      if (!transform || transform.length < 6) {
        positionedItems.push({
          text,
          x: 0,
          y: 0,
        });

        continue;
      }

      positionedItems.push({
        text,
        x: Number(transform[4]) || 0,
        y: Number(transform[5]) || 0,
      });
    }


    positionedItems.sort((a, b) => {
      if (Math.abs(a.y - b.y) > 3) {
        return b.y - a.y;
      }

      return a.x - b.x;
    });

    const pageLines: PdfLine[][] = [];

    for (const item of positionedItems) {
      const currentLine = pageLines[pageLines.length - 1];

      if (!currentLine) {
        pageLines.push([item]);
        continue;
      }

      const referenceY = currentLine[0].y;

      if (Math.abs(referenceY - item.y) <= 3) {
        currentLine.push(item);
      } else {
        pageLines.push([item]);
      }
    }

    for (const line of pageLines) {
      line.sort((a, b) => a.x - b.x);

      const text = normaliseText(
        line
          .map((item) => item.text)
          .join(" "),
      );

      if (text) {
        lines.push(text);
      }
    }
  }

  return lines;
}

// ============================================================================
// Generic extraction helpers
// ============================================================================

const MONEY_PATTERN =
  /£\s*[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})/g;

const NUMBER_PATTERN =
  /[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?/g;

function findMoneyValues(text: string): number[] {
  return Array.from(text.matchAll(MONEY_PATTERN))
    .map((match) => parseMoney(match[0]))
    .filter((value): value is number => value !== null);
}

function findNumbers(text: string): number[] {
  return Array.from(text.matchAll(NUMBER_PATTERN))
    .map((match) => parseNumber(match[0]))
    .filter((value): value is number => value !== null);
}

function extractFirstMoneyAfterLabel(
  lines: string[],
  labels: RegExp[],
): ExtractedValue | null {
  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (!labels.some((label) => label.test(normalised))) {
      continue;
    }

    const values = findMoneyValues(line);

    if (values.length === 0) {
      continue;
    }

    return {
      value: values[0],
      source: line,
      confidence: 0.9,
    };
  }

  return null;
}

function extractMoneyFromExactLine(
  lines: string[],
  labelPattern: RegExp,
): ExtractedValue | null {
  for (const line of lines) {
    const match = line.match(labelPattern);

    if (!match) {
      continue;
    }

    const remainder = line.slice(match.index! + match[0].length);
    const values = findMoneyValues(remainder);

    if (values.length > 0) {
      return {
        value: values[0],
        source: line,
        confidence: 0.95,
      };
    }
  }

  return null;
}

// ============================================================================
// Tax code
// ============================================================================

function extractTaxCode(lines: string[]): string | null {
  const taxCodePattern =
    /\btax\s*code\b\s*:?\s*((?:S|C)?(?:K\d+|\d{3,5}L|BR|D0|D1|0T|NT)(?:\s*(?:W1|M1|X))?)/i;

  for (const line of lines) {
    const match = line.match(taxCodePattern);

    if (match?.[1]) {
      return normaliseText(match[1]).toUpperCase();
    }
  }

  // Some payroll systems print the tax code without the "Tax code" label.
  const standalonePattern =
    /\b((?:S|C)?(?:K\d+|\d{3,5}L|BR|D0|D1|0T|NT)(?:\s*(?:W1|M1|X))?)\b/i;

  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (
      normalised.includes("national insurance") ||
      normalised.includes("insurance number")
    ) {
      continue;
    }

    const match = line.match(standalonePattern);

    if (match?.[1]) {
      return normaliseText(match[1]).toUpperCase();
    }
  }

  return null;
}

// ============================================================================
// Date / frequency
// ============================================================================

function extractPayDate(lines: string[]): Date | null {
  const monthNames =
    "(January|February|March|April|May|June|July|August|September|October|November|December)";

  const patterns = [
    new RegExp(
      `(?:month\\s+ending|pay\\s+date|payment\\s+date|period\\s+ending)\\s+` +
        `(\\d{1,2})\\s+${monthNames}\\s+(\\d{4})`,
      "i",
    ),
    new RegExp(
      `(\\d{1,2})\\s+${monthNames}\\s+(\\d{4})`,
      "i",
    ),
    new RegExp(
      `(?:month\\s+ending|pay\\s+date|payment\\s+date)\\s+` +
        `(\\d{1,2})[/-](\\d{1,2})[/-](\\d{4})`,
      "i",
    ),
  ];

  for (const line of lines) {
    for (const pattern of patterns) {
      const match = line.match(pattern);

      if (!match) {
        continue;
      }

      if (match.length >= 4 && Number.isNaN(Number(match[2]))) {
        // Month-name format.
        const day = Number(match[1]);
        const monthName = match[2];
        const year = Number(match[3]);

        const monthIndex = new Date(
          `${monthName} 1, ${year}`,
        ).getMonth();

        const date = new Date(year, monthIndex, day);

        if (!Number.isNaN(date.getTime())) {
          return date;
        }
      }

      if (match.length >= 4 && !Number.isNaN(Number(match[2]))) {
        // Numeric format.
        const day = Number(match[1]);
        const month = Number(match[2]);
        const year = Number(match[3]);

        const date = new Date(year, month - 1, day);

        if (!Number.isNaN(date.getTime())) {
          return date;
        }
      }
    }
  }

  return null;
}

function detectFrequency(
  lines: string[],
): "MONTHLY" | "WEEKLY" | null {
  const text = normaliseForMatching(lines.join(" "));

  if (
    /\bmonthly\s+(pay|salary|rate)\b/i.test(text) ||
    /\bmonthly\b/i.test(text) ||
    /\bmonth\s+ending\b/i.test(text)
  ) {
    return "MONTHLY";
  }

  if (
    /\bweekly\s+(pay|salary|rate)\b/i.test(text) ||
    /\bweekly\b/i.test(text) ||
    /\bweek\s+ending\b/i.test(text)
  ) {
    return "WEEKLY";
  }

  return null;
}

// ============================================================================
// Gross pay
// ============================================================================

function extractGrossPay(lines: string[]): ExtractedValue | null {

  const candidates: ExtractedValue[] = [];

  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (/\byear\s+to\s+date\b|\bytd\b/i.test(normalised)) {
      continue;
    }

    if (
      /\bmonthly\s+pay\b/i.test(normalised) ||
      /\bgross\s+pay\b/i.test(normalised) ||
      /\bgross\s+salary\b/i.test(normalised) ||
      /\bbasic\s+pay\b/i.test(normalised) ||
      /\btaxable\s+gross\s+pay\b/i.test(normalised)
    ) {
      const values = findMoneyValues(line);

      if (values.length > 0) {
        candidates.push({
          value: values[0],
          source: line,
          confidence: 0.95,
        });
      }
    }
  }

  if (candidates.length > 0) {
    // Prefer "gross pay" / "monthly pay" over generic labels.
    const preferred = candidates.find((candidate) =>
      /\b(monthly\s+pay|gross\s+pay|gross\s+salary)\b/i.test(
        candidate.source,
      ),
    );

    return preferred ?? candidates[0];
  }

  return null;
}

// ============================================================================
// Income tax
// ============================================================================

function extractIncomeTax(lines: string[]): ExtractedValue | null {
  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    // Don't accidentally extract employer tax or YTD tax.
    if (
      /\byear\s+to\s+date\b|\bytd\b/i.test(normalised) ||
      /employer/i.test(normalised)
    ) {
      continue;
    }

    if (
      /\bincome\s+tax\b/i.test(normalised) ||
      /\bpaye\b/i.test(normalised) ||
      /^\s*tax\b/i.test(normalised)
    ) {
      const values = findMoneyValues(line);

      if (values.length > 0) {
        return {
          value: values[0],
          source: line,
          confidence: /\bincome\s+tax\b|\bpaye\b/i.test(normalised)
            ? 0.97
            : 0.9,
        };
      }
    }
  }

  return null;
}

// ============================================================================
// National Insurance
// ============================================================================

function extractNationalInsurance(
  lines: string[],
): ExtractedValue | null {
  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (
      /\byear\s+to\s+date\b|\bytd\b/i.test(normalised) ||
      /employer/i.test(normalised)
    ) {
      continue;
    }

    if (
      /\bnational\s+insurance\b/i.test(normalised) ||
      /\bemployee\s+ni\b/i.test(normalised)
    ) {
      const values = findMoneyValues(line);

      if (values.length > 0) {
        return {
          value: values[0],
          source: line,
          confidence: 0.97,
        };
      }
    }
  }

  return null;
}

// ============================================================================
// Pension
// ============================================================================

function extractPension(
  lines: string[],
): ExtractedValue | null {


  const employeePatterns = [
    /\bemployee\s+pension\b/i,
    /\bpension\s+employee\b/i,
    /\bemployee\s+pension\s+contribution\b/i,
  ];

  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (/employer\s+pension/i.test(normalised)) {
      continue;
    }

    if (
      employeePatterns.some((pattern) => pattern.test(normalised)) ||
      (
        /\bpension\b/i.test(normalised) &&
        !/employer/i.test(normalised)
      )
    ) {
      const values = findMoneyValues(line);

      if (values.length > 0) {
        return {
          value: values[0],
          source: line,
          confidence: employeePatterns.some((pattern) =>
            pattern.test(normalised),
          )
            ? 0.97
            : 0.85,
        };
      }
    }
  }

  return null;
}

// ============================================================================
// Net pay
// ============================================================================

function extractNetPay(
  lines: string[],
): ExtractedValue | null {
  /*
   * Prefer an explicitly labelled "Net pay".
   *
   * Do NOT calculate net pay here. The payslip is the source of truth for
   * what it actually says. Calculation/reconciliation belongs elsewhere.
   */

  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (/\bnet\s+pay\b/i.test(normalised)) {
      const values = findMoneyValues(line);

      if (values.length > 0) {
        return {
          value: values[0],
          source: line,
          confidence: 0.99,
        };
      }
    }
  }

  return null;
}

// ============================================================================
// Hourly rate / hours
// ============================================================================

function extractHourlyRate(
  lines: string[],
): ExtractedValue | null {
  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (
      /\bhourly\s+rate\b/i.test(normalised) ||
      /\brate\s+per\s+hour\b/i.test(normalised)
    ) {
      const values = findMoneyValues(line);

      if (values.length > 0) {
        return {
          value: values[0],
          source: line,
          confidence: 0.95,
        };
      }
    }
  }

  return null;
}

function extractHours(
  lines: string[],
): ExtractedValue | null {
  for (const line of lines) {
    const normalised = normaliseForMatching(line);

    if (
      !/\bhours?\b/i.test(normalised) ||
      /\byear\s+to\s+date\b|\bytd\b/i.test(normalised)
    ) {
      continue;
    }

    const values = findNumbers(line);

    if (values.length > 0) {
      return {
        value: values[0],
        source: line,
        confidence: 0.85,
      };
    }
  }

  return null;
}

// ============================================================================
// Validation
// ============================================================================

function validateExtraction(
  result: ExtractionResult,
): {
  confidence: "high" | "low";
  reasons: string[];
} {
  const reasons: string[] = [];

  const required = [
    result.grossPay,
    result.incomeTax,
    result.nationalInsurance,
    result.netPay,
    result.taxCode,
  ];

  if (required.some((value) => value === null)) {
    reasons.push("One or more required payslip fields could not be read.");
  }

  if (
    result.grossPay &&
    result.incomeTax &&
    result.nationalInsurance &&
    result.netPay
  ) {
    const pension = result.pensionContribution?.value ?? 0;

    const expectedNet =
      result.grossPay.value -
      result.incomeTax.value -
      result.nationalInsurance.value -
      pension;

    if (!nearlyEqual(expectedNet, result.netPay.value)) {
      reasons.push(
        `The extracted deductions do not fully reconcile with net pay. ` +
        `Expected approximately £${expectedNet.toFixed(2)}, ` +
        `but the payslip reports £${result.netPay.value.toFixed(2)}.`,
      );
    }
  }

  if (!result.frequency) {
    reasons.push("Pay frequency could not be determined.");
  }

  if (!result.payDate) {
    reasons.push("Pay date could not be determined.");
  }

  const confidenceValues = [
    result.grossPay?.confidence,
    result.incomeTax?.confidence,
    result.nationalInsurance?.confidence,
    result.pensionContribution?.confidence,
    result.netPay?.confidence,
  ].filter((value): value is number => value !== undefined);

  const averageConfidence =
    confidenceValues.length > 0
      ? confidenceValues.reduce((sum, value) => sum + value, 0) /
        confidenceValues.length
      : 0;


  if (
    required.some((value) => value === null) ||
    averageConfidence < 0.85
  ) {
    return {
      confidence: "low",
      reasons,
    };
  }

  return {
    confidence: "high",
    reasons,
  };
}

// ============================================================================
// Main parser
// ============================================================================

export async function parsePayslipPdf(
  file: File,
  jobLabel: string,
): Promise<ParseResult> {
  try {
    if (!file) {
      return {
        success: false,
        payslip: null,
        missingFields: [
          "grossPay",
          "incomeTax",
          "nationalInsurance",
          "netPay",
          "taxCode",
        ],
        confidence: "low",
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
        ],
        confidence: "low",
      };
    }

    const lines = await extractPdfLines(file);

    if (lines.length === 0) {
      return {
        success: false,
        payslip: null,
        missingFields: [
          "grossPay",
          "incomeTax",
          "nationalInsurance",
          "netPay",
          "taxCode",
        ],
        confidence: "low",
      };
    }

    const extraction: ExtractionResult = {
      grossPay: extractGrossPay(lines),
      incomeTax: extractIncomeTax(lines),
      nationalInsurance: extractNationalInsurance(lines),
      pensionContribution: extractPension(lines),
      netPay: extractNetPay(lines),
      taxCode: extractTaxCode(lines),
      hourlyRate: extractHourlyRate(lines),
      hours: extractHours(lines),
      payDate: extractPayDate(lines),
      frequency: detectFrequency(lines),
    };

    const validation = validateExtraction(extraction);

    const missingFields: (keyof Payslip)[] = [];

    if (!extraction.grossPay) {
      missingFields.push("grossPay");
    }

    if (!extraction.incomeTax) {
      missingFields.push("incomeTax");
    }

    if (!extraction.nationalInsurance) {
      missingFields.push("nationalInsurance");
    }

    if (!extraction.netPay) {
      missingFields.push("netPay");
    }

    if (!extraction.taxCode) {
      missingFields.push("taxCode");
    }

 
    if (missingFields.length > 0) {
      return {
        success: false,
        payslip: null,
        missingFields,
        confidence: "low",
      };
    }

    const payDate = extraction.payDate ?? new Date();

    const month = `${payDate.getFullYear()}-${String(
      payDate.getMonth() + 1,
    ).padStart(2, "0")}`;

    const pensionContribution =
      extraction.pensionContribution?.value ?? 0;

    const payslip: Payslip = {
      id: crypto.randomUUID(),
      jobLabel: jobLabel.trim() || "Primary job",
      month,
      hourlyRate: extraction.hourlyRate?.value ?? null,

      grossPay: extraction.grossPay!.value,
      incomeTax: extraction.incomeTax!.value,
      nationalInsurance: extraction.nationalInsurance!.value,
      pensionContribution,
      netPay: extraction.netPay!.value,

      taxCode: extraction.taxCode!,
      scannedAt: Date.now(),
    };

    return {
      success: true,
      payslip,
      missingFields: [],
      confidence: validation.confidence,
    };
  } catch (error) {
    console.error("Payslip PDF parsing failed:", error);

    return {
      success: false,
      payslip: null,
      missingFields: [
        "grossPay",
        "incomeTax",
        "nationalInsurance",
        "netPay",
        "taxCode",
      ],
      confidence: "low",
    };
  }
}

// ============================================================================
// Manual entry
// ============================================================================

export function createManualPayslip(
  input: ManualPayslipInput,
): Payslip {
  const grossPay = Number(input.grossPay);
  const incomeTax = Number(input.incomeTax);
  const nationalInsurance = Number(input.nationalInsurance);
  const pensionContribution = Number(
    input.pensionContribution ?? 0,
  );
  const netPay = Number(input.netPay);

  const hourlyRate =
    input.hourlyRate === "" ||
    input.hourlyRate == null
      ? null
      : Number(input.hourlyRate);

  const taxCode = String(input.taxCode || "")
    .trim()
    .toUpperCase();

  if (
    !Number.isFinite(grossPay) ||
    !Number.isFinite(incomeTax) ||
    !Number.isFinite(nationalInsurance) ||
    !Number.isFinite(netPay)
  ) {
    throw new TypeError(
      "Gross pay, net pay, income tax, and National Insurance are required.",
    );
  }

  if (!taxCode) {
    throw new TypeError("Tax code is required.");
  }

  return {
    id: crypto.randomUUID(),
    jobLabel: input.jobLabel?.trim() || "Primary job",
    month: input.month?.trim() || currentMonthKey(),

    hourlyRate:
      hourlyRate !== null && Number.isFinite(hourlyRate)
        ? hourlyRate
        : null,

    grossPay,
    incomeTax,
    nationalInsurance,

    pensionContribution:
      Number.isFinite(pensionContribution)
        ? pensionContribution
        : 0,

    netPay,
    taxCode,
    scannedAt: Date.now(),
  };
}

// ============================================================================
// Utility
// ============================================================================

function currentMonthKey(): string {
  const now = new Date();

  return `${now.getFullYear()}-${String(
    now.getMonth() + 1,
  ).padStart(2, "0")}`;
}