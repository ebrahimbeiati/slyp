// Builds the "copy to payroll" message. Every clause comes straight from
// AnalysisResult - the code the backend already computed. Nothing here is
// re-derived or reformatted into a new figure, and nothing here is
// model-generated: this file never calls an LLM and never will.
//
// A field that failed the confidence gate (extract.unreadable_fields)
// drops its clause entirely rather than printing "undefined" or "£null" -
// see the `line()` helper below.

import type { AnalysisResult, PayslipExtract } from "@/app/Types/Types";

function gbp(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `£${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** One optional line of the message. Renders nothing at all - not an
 * empty string that would leave a blank line, not a line with a gap in
 * it - when the field is gated or genuinely absent. */
function line(
  extract: PayslipExtract,
  field: string,
  value: string | null,
  label: string,
): string | null {
  if (extract.unreadable_fields.includes(field)) return null;
  if (value === null) return null;
  return `${label}: ${gbp(value)}`;
}

export function buildPayrollMessage(result: AnalysisResult): string {
  if (result.status !== "ok" || !result.extract) {
    return "No payslip analysis is available to share.";
  }

  const extract = result.extract;
  const parts: string[] = [];

  parts.push("Payslip check (via Slyp)");
  if (extract.period.tax_year) {
    parts.push(`Tax year: ${extract.period.tax_year}`);
  }
  if (extract.tax_code.value && !extract.unreadable_fields.includes("tax_code.value")) {
    parts.push(`Tax code: ${extract.tax_code.value}`);
  }

  const figures = [
    line(extract, "pay.gross_this_period", extract.pay.gross_this_period, "Gross pay"),
    line(extract, "deductions.income_tax", extract.deductions.income_tax, "Income tax"),
    line(extract, "deductions.national_insurance", extract.deductions.national_insurance, "National Insurance"),
    line(extract, "deductions.student_loan", extract.deductions.student_loan, "Student loan"),
    line(extract, "deductions.pension_employee", extract.deductions.pension_employee, "Pension"),
    line(extract, "net_pay", extract.net_pay, "Net pay"),
  ].filter((l): l is string => l !== null);

  if (figures.length > 0) {
    parts.push("", ...figures);
  }

  const actionFindings = result.findings.filter((f) => f.severity === "action");
  if (actionFindings.length > 0) {
    parts.push("", "Things worth checking:");
    for (const finding of actionFindings) {
      parts.push(`- ${finding.title}`);
    }
  }

  if (extract.unreadable_fields.length > 0) {
    parts.push(
      "",
      `Not confidently readable from the payslip: ${extract.unreadable_fields.join(", ")}.`,
    );
  }

  return parts.join("\n");
}
