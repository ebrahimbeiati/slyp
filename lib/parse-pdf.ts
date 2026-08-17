import type { Payslip, ParseResult } from "../app/Types/Types";

// ---------------------------------------------------------------------------
// Build spec §2: client-side extraction, no backend, no file leaves the
// device. This makes "we forget the file" literally true.
//
// Build spec §9 (the one thing not to skip): the regexes below are tuned
// against ONE payslip template. Test against a payslip nobody on the team
// designed the regex around before demo day. If it fails, the app must fall
// back to manual entry (see the `success: false` path) — never crash.
// ---------------------------------------------------------------------------

// TODO(team): confirm which template you're targeting (ADP / Sage / your
// employer's standard) and tune these patterns against 2-3 real anonymised
// samples BEFORE the hackathon starts, per spec §2. These are reasonable
// starting points, not tuned patterns.
const PATTERNS = {
  netPay: /net\s*pay\s*[:£]?\s*£?\s*([\d,]+\.\d{2})/i,
  grossPay: /gross\s*pay\s*[:£]?\s*£?\s*([\d,]+\.\d{2})/i,
  taxCode: /tax\s*code\s*:?\s*(\d{1,4}[A-Z]|BR|D0|D1|0T|NT)/i,
  incomeTax: /(?:income\s*tax|paye)\s*[:£]?\s*£?\s*([\d,]+\.\d{2})/i,
  nationalInsurance: /national\s*insurance\s*[:£]?\s*£?\s*([\d,]+\.\d{2})/i,
  pensionContribution: /pension\s*[:£]?\s*£?\s*([\d,]+\.\d{2})/i,
  hourlyRate: /hourly\s*rate\s*[:£]?\s*£?\s*([\d,]+\.\d{2})/i,
  hours: /hours?\s*:?\s*(\d[\d,]*\.?\d*)/i,
};

function parseNumber(raw: string | undefined): number | null {
  if (!raw) return null;
  const n = Number(raw.replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

function extractField(text: string, pattern: RegExp): string | undefined {
  return text.match(pattern)?.[1];
}

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

export function createManualPayslip(input: ManualPayslipInput): Payslip {
  const grossPay = Number(input.grossPay);
  const incomeTax = Number(input.incomeTax);
  const nationalInsurance = Number(input.nationalInsurance);
  const pensionContribution = Number(input.pensionContribution ?? 0);
  const netPay = Number(input.netPay);
  const hourlyRate = input.hourlyRate === "" || input.hourlyRate == null ? null : Number(input.hourlyRate);
  const taxCode = String(input.taxCode || "").trim().toUpperCase();

  if (!Number.isFinite(grossPay) || !Number.isFinite(incomeTax) || !Number.isFinite(nationalInsurance) || !Number.isFinite(netPay)) {
    throw new TypeError("Gross pay, net pay, income tax, and National Insurance are required.");
  }

  if (!taxCode) {
    throw new TypeError("Tax code is required.");
  }

  return {
    id: crypto.randomUUID(),
    jobLabel: input.jobLabel?.trim() || "Primary job",
    month: input.month?.trim() || currentMonthKey(),
    hourlyRate: Number.isFinite(hourlyRate as number) ? (hourlyRate as number) : null,
    grossPay,
    incomeTax,
    nationalInsurance,
    pensionContribution: Number.isFinite(pensionContribution) ? pensionContribution : 0,
    netPay,
    taxCode,
    scannedAt: Date.now(),
  };
}

/**
 * Extracts raw text from a PDF File entirely in the browser via pdf.js.
 * Dynamically imported so pdf.js (and its worker) never end up in a server bundle.
 */
async function extractTextFromPdf(file: File): Promise<string> {
  const pdfjsLib = await import("pdfjs-dist");
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url
  ).toString();

  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

  let fullText = "";
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum);
    const content = await page.getTextContent();
    fullText += content.items
      .map((item) => ("str" in item ? item.str : ""))
      .join(" ") + "\n";
  }
  return fullText;
}

/**
 * Parses a payslip PDF client-side and returns either a populated Payslip
 * (fields we're confident about) or a list of missing fields the manual
 * entry form should fill in. Never throws for a bad/unsupported PDF —
 * spec §2's fallback requirement is enforced here, not left to the caller.
 */
export async function parsePayslipPdf(file: File, jobLabel: string): Promise<ParseResult> {
  try {
    const text = await extractTextFromPdf(file);

    const netPay = parseNumber(extractField(text, PATTERNS.netPay));
    const grossPay = parseNumber(extractField(text, PATTERNS.grossPay));
    const taxCode = extractField(text, PATTERNS.taxCode)?.toUpperCase() ?? null;
    const incomeTax = parseNumber(extractField(text, PATTERNS.incomeTax));
    const nationalInsurance = parseNumber(extractField(text, PATTERNS.nationalInsurance));
    const pensionContribution = parseNumber(extractField(text, PATTERNS.pensionContribution)) ?? 0;

    // Hourly rate: use it if printed; otherwise derive from gross ÷ hours;
    // otherwise leave null and the part-time calculator hides itself (spec §2 item 7).
    let hourlyRate = parseNumber(extractField(text, PATTERNS.hourlyRate));
    if (hourlyRate === null && grossPay !== null) {
      const hours = parseNumber(extractField(text, PATTERNS.hours));
      if (hours && hours > 0) hourlyRate = grossPay / hours;
    }

    const requiredFields: Array<[keyof Payslip, unknown]> = [
      ["netPay", netPay],
      ["grossPay", grossPay],
      ["taxCode", taxCode],
      ["incomeTax", incomeTax],
      ["nationalInsurance", nationalInsurance],
    ];
    const missingFields = requiredFields.filter(([, v]) => v === null || v === undefined).map(([k]) => k);

    if (missingFields.length > 0) {
      return { success: false, payslip: null, missingFields, confidence: "low" };
    }

    const payslip: Payslip = {
      id: crypto.randomUUID(),
      jobLabel,
      month: currentMonthKey(),
      hourlyRate,
      grossPay: grossPay as number,
      incomeTax: incomeTax as number,
      nationalInsurance: nationalInsurance as number,
      pensionContribution,
      netPay: netPay as number,
      taxCode: taxCode as string,
      scannedAt: Date.now(),
    };

    return { success: true, payslip, missingFields: [], confidence: "high" };
  } catch {
    // Parsing threw entirely (corrupt file, scanned image with no text layer, etc.)
    // — treat exactly like a low-confidence parse so the UI path is identical.
    return {
      success: false,
      payslip: null,
      missingFields: ["netPay", "grossPay", "taxCode", "incomeTax", "nationalInsurance"],
      confidence: "low",
    };
  }
}

function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}