// Mirrors slyp/contract.py exactly - that file is the wire format, this is
// its TypeScript shape. Keep the two in sync by hand; if contract.py
// changes, this file needs the matching edit.
//
// Money fields are `string`, not `number`: pydantic serialises Decimal to
// a JSON string (confirmed against a live /analyse response -
// "gross_this_period":"583.55", not 583.55). Never parseFloat() one of
// these for a figure you display directly - only for things like bar-chart
// widths where a float rounding error is invisible. The number the user
// sees must come from the string as printed by the API, unmodified.

export type Severity = "clear" | "advisory" | "action";
export type Frequency = "monthly" | "weekly";

export interface Period {
  pay_date: string | null; // ISO date, e.g. "2026-03-31"
  period_number: number | null;
  frequency: Frequency | null;
  tax_year: string | null; // e.g. "2026/27"
}

export interface TaxCodeRead {
  value: string | null;
}

export interface Pay {
  hourly_rate: string | null;
  hours: string | null;
  gross_this_period: string | null;
  gross_ytd: string | null;
}

export type OtherDeductionType =
  | "union"
  | "court_order"
  | "charity"
  | "loan"
  | "other";

export interface OtherDeduction {
  type: OtherDeductionType;
  amount: string;
}

export interface Deductions {
  income_tax: string | null;
  income_tax_ytd: string | null;
  national_insurance: string | null;
  national_insurance_ytd: string | null;
  ni_category: string | null;
  pension_employee: string | null;
  pension_employer: string | null;
  pension_percent: string | null;
  student_loan: string | null;
  student_loan_plan: "1" | "2" | "4" | "5" | "PG" | null;
  other: OtherDeduction[];
}

export interface Source {
  filename: string | null;
  pages: number | null;
  scanned_at: string; // ISO datetime
}

export interface PayslipExtract {
  source: Source;
  employer_name: string | null;
  period: Period;
  tax_code: TaxCodeRead;
  pay: Pay;
  deductions: Deductions;
  net_pay: string | null;
  confidence: Record<string, number>;
  // Dotted paths that failed the confidence gate. A rule never runs on a
  // field listed here - render this state explicitly, never as blank
  // space or a zero. See Finding.source_fields.
  unreadable_fields: string[];
  warnings: string[];
  reconciles: boolean | null;
  previous_employment_ytd_present: boolean;
}

export interface Estimate {
  label: string;
  amount_gbp: string;
  is_estimate: boolean;
}

export interface Finding {
  id: string;
  severity: Severity;
  title: string;
  explanation: string;
  estimate: Estimate | null;
  next_step: string | null;
  projection_key: string | null;
  // Extract fields this finding depends on. Cross-reference against
  // extract.unreadable_fields to know why a finding might be conditional.
  source_fields: string[];
}

export interface ProjectionPoint {
  label: string;
  path_a: string;
  path_b: string;
}

export interface Projection {
  key: string;
  title: string;
  path_a_label: string;
  path_b_label: string;
  unit: "gbp";
  points: ProjectionPoint[];
  caveat: string;
}

export interface Score {
  // null when no check applied - not 0, which would read as a failing
  // payslip rather than an unscored one.
  value: number | null;
  checks_passed: number;
  checks_run: number;
  movers: string[];
  // Plain-English reasons a check did not apply. Neither passes nor
  // failures, and excluded from checks_run.
  not_applicable: string[];
}

export interface Verdict {
  headline: string;
  severity: Severity;
}

export type AnalysisStatus = "ok" | "unreadable" | "not_a_payslip" | "unsupported";

/**
 * Personal Allowance used to date. Computed in Python and gated there -
 * see analysis.build_allowance_usage(). The frontend renders `statement`
 * or renders nothing; it never derives the figure, and there is no
 * "remaining" field on purpose, because a number named that gets rendered
 * as "left to earn tax-free", which is a projection.
 */
export interface AllowanceUsage {
  used_gbp: string;
  allowance_gbp: string;
  statement: string;
}

export interface AnalysisResult {
  status: AnalysisStatus;
  failure_reason: string | null;
  extract: PayslipExtract | null;
  verdict: Verdict | null;
  findings: Finding[];
  projections: Projection[];
  score: Score | null;
  /** Null whenever any guard suppressed it, which is the common case. */
  allowance_usage: AllowanceUsage | null;
  is_example_data: boolean;
}
