// Builds the "copy for payroll" message.
//
// This is a message one person sends another, usually pasted into an email
// or Teams and sent as-is. So: prose, short paragraphs, plain sentences.
// No bullets, no label-colon-value lines, no arrows or dashes as
// decoration, no markdown, no branding. It has to survive plain text
// because plain text is where it lands.
//
// Every figure comes straight from AnalysisResult - the numbers the
// backend already computed. Nothing here is re-derived, and nothing here
// is model-generated: this file never calls an LLM and never will.
//
// A field that failed the confidence gate (extract.unreadable_fields) does
// not produce a hedged sentence - the sentence that would have used it is
// not written at all. See `readable()`.

import type { AnalysisResult, Finding, PayslipExtract } from "@/app/Types/Types";

function gbp(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `£${n.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * A figure formatted for a sentence, or null if it must not be mentioned.
 *
 * Null means the sentence that wanted it gets dropped entirely. That is
 * the whole confidence-gate contract expressed in one helper: a figure we
 * could not read confidently is not written as "unknown" or "£0.00" or an
 * empty gap in a sentence to payroll, it simply does not appear.
 */
function readable(
  extract: PayslipExtract,
  field: string,
  value: string | null,
): string | null {
  if (extract.unreadable_fields.includes(field)) return null;
  if (value === null) return null;
  return gbp(value);
}

/** "28 August 2026" from "2026-08-28", without going through Date - a
 *  UTC-midnight parse can land on the previous day west of Greenwich. */
function longDate(iso: string | null): string | null {
  if (!iso) return null;
  const [year, month, day] = iso.split("-").map(Number);
  const months = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  if (!year || !month || !day || !months[month - 1]) return null;
  return `${day} ${months[month - 1]} ${year}`;
}

/**
 * How the tax code is being applied, in the words the payslip uses.
 *
 * Payroll cannot diagnose a tax query without this. Deliberately a
 * statement about what is PRINTED rather than an inference: when there is
 * a W1/M1/X suffix we name it, and when there is not we say it is not
 * shown rather than asserting the code is cumulative. The contract only
 * carries the code as text (TaxCodeRead.value), so "no suffix" is
 * evidence, not proof - and a wrong claim about the basis is exactly the
 * thing that would send payroll looking in the wrong place.
 */
function basisClause(code: string): string {
  return /\s?(W1|M1|X)$/i.test(code.trim())
    ? ", which is a week 1 / month 1 basis"
    : ", with no week 1 or month 1 marking shown on the payslip";
}

/** The conditional branch of the emergency-code estimate. The backend
 *  writes the condition into the Estimate's own label, so the caveat
 *  travels with the number rather than being re-derived here. Pinned by
 *  verify/final_payroll_message.test.ts so a backend rewording fails
 *  loudly instead of silently dropping the caveat. */
const CONDITIONAL_ESTIMATE = "only employment this tax year";

function find(findings: Finding[], id: string): Finding | undefined {
  return findings.find((finding) => finding.id === id);
}

function amount(finding: Finding | undefined): string | null {
  return finding?.estimate?.amount_gbp ?? null;
}

export function buildPayrollMessage(result: AnalysisResult): string {
  if (result.status !== "ok" || !result.extract) {
    return "No payslip analysis is available to share.";
  }

  const extract = result.extract;
  const findings = result.findings;

  const gross = readable(extract, "pay.gross_this_period", extract.pay.gross_this_period);
  const tax = readable(extract, "deductions.income_tax", extract.deductions.income_tax);
  const net = readable(extract, "net_pay", extract.net_pay);
  const pension = readable(extract, "deductions.pension_employee", extract.deductions.pension_employee);
  const code = extract.unreadable_fields.includes("tax_code.value")
    ? null
    : extract.tax_code.value;

  const when = longDate(extract.period.pay_date);
  const period = when ? `my payslip dated ${when}` : "my payslip for this period";

  const reconciliation = find(findings, "payslip_does_not_reconcile");
  const taxVariance = find(findings, "income_tax_differs_from_calculation");
  const niVariance = find(findings, "national_insurance_differs_from_calculation");
  const netVariance = find(findings, "net_pay_differs_from_calculation");
  const pensionVariance = find(findings, "pension_differs_from_calculation");
  const emergency = find(findings, "tax_code_emergency_basis");
  const brHere = find(findings, "tax_code_br_allowance_elsewhere");

  const paragraphs: string[] = [];
  // Whether each concern is about a FIGURE or about the CODE. A message
  // whose only concern is an emergency tax code should not open by saying
  // the figures need checking - the figures may be perfectly correct for
  // the code that was applied, which is the whole point of raising it.
  const kinds: Array<"figure" | "code"> = [];
  let request: string | null = null;

  // ------------------------------------------------------------------
  // Income tax variance, and anything that follows from it.
  // ------------------------------------------------------------------
  //
  // The net-pay variance is the same discrepancy restated: expected_net is
  // only populated when the payslip reconciles, and under that condition
  // the net difference IS the sum of the component differences. So it is
  // never a second thing to raise.
  //
  // A reconciliation break is a different comparison - the payslip against
  // itself, rather than against the engine - so the two are only linked
  // when they come to the same amount, and even then only as far as "would
  // also account for". The engine does not establish cause and this
  // message must not imply it does.
  const taxDiff = amount(taxVariance);

  if (taxVariance && taxDiff && gross && tax) {
    const reconDiff = amount(reconciliation);
    const netDiff = amount(netVariance);
    const alsoExplains =
      (reconDiff !== null && reconDiff === taxDiff) ||
      (netDiff !== null && netDiff === taxDiff);

    const higher = taxVariance.title.toLowerCase().includes("higher");
    const direction = higher ? "higher" : "lower";

    let sentence =
      `The gross is ${gross} with ${tax} of income tax deducted` +
      (code ? ` on tax code ${code}${basisClause(code)}` : "") +
      `. That looks around ${gbp(taxDiff)} ${direction} than I’d expect`;

    if (alsoExplains && net) {
      sentence +=
        `, which would also account for the net pay of ${net} not matching` +
        ` the other figures by the same amount`;
    }

    paragraphs.push(sentence + ".");
    kinds.push("figure");
    request =
      "Could you check whether the correct tax code and basis were applied for this period?";
  } else if (reconciliation && amount(reconciliation) && gross && net) {
    // Reconciliation break with no tax variance to explain it.
    paragraphs.push(
      `The gross is ${gross} and the net pay is ${net}, but the deductions` +
        ` shown leave about ${gbp(amount(reconciliation)!)} unaccounted for` +
        ` between the two.`,
    );
    kinds.push("figure");
    request = "Could you confirm the deductions applied for this period?";
  }

  // ------------------------------------------------------------------
  // Emergency / non-cumulative basis.
  // ------------------------------------------------------------------
  if (emergency && code) {
    const overpaid = amount(emergency);
    let sentence = `My tax code is shown as ${code}${basisClause(code)}`;

    if (overpaid) {
      const conditional = emergency.estimate!.label.includes(CONDITIONAL_ESTIMATE);
      sentence += conditional
        ? `. If this has been my only employment this tax year, I think that may` +
          ` have led to around ${gbp(overpaid)} more income tax being deducted` +
          ` so far than a cumulative code would have`
        : `. As this has been my only employment this tax year, I think that may` +
          ` have led to around ${gbp(overpaid)} more income tax being deducted` +
          ` so far than a cumulative code would have`;
    } else {
      sentence +=
        `, so each payslip is being taxed on its own rather than across the` +
        ` year so far`;
    }

    paragraphs.push(sentence + ".");
    kinds.push("code");
    request ??=
      "Could you confirm which tax code HMRC has issued for me, and whether it can be applied on a cumulative basis?";
  }

  // ------------------------------------------------------------------
  // BR where the allowance is expected here.
  // ------------------------------------------------------------------
  if (brHere && code) {
    paragraphs.push(
      `My tax code is shown as ${code}${basisClause(code)}. That taxes all of` +
        ` this pay at the basic rate with no personal allowance applied here.` +
        ` As far as I know this is my only job, so I’d expect my allowance to` +
        ` be applied against it.`,
    );
    kinds.push("code");
    request ??= "Could you confirm which tax code HMRC has issued for me?";
  }

  // ------------------------------------------------------------------
  // National Insurance and pension, only when they are the concern.
  // ------------------------------------------------------------------
  const niDiff = amount(niVariance);
  if (niVariance && niDiff) {
    paragraphs.push(
      `The National Insurance deducted also looks around ${gbp(niDiff)} away` +
        ` from what I’d expect for this period.`,
    );
    kinds.push("figure");
    request ??=
      "Could you check which National Insurance category is being applied to me?";
  }

  const pensionDiff = amount(pensionVariance);
  if (pensionVariance && pensionDiff && pension) {
    paragraphs.push(
      `The pension contribution of ${pension} is also around` +
        ` ${gbp(pensionDiff)} away from what I’d expect.`,
    );
    kinds.push("figure");
    request ??=
      "Could you check my pension enrolment and the contribution rate being applied?";
  }

  // ------------------------------------------------------------------
  // Assemble.
  // ------------------------------------------------------------------
  if (paragraphs.length === 0) {
    // Nothing to raise. Still worth a message, because the one thing an
    // employee genuinely cannot verify alone is which code HMRC issued.
    const opening = `Hi,\n\nI’ve been going through ${period} and the figures look consistent to me as far as I can tell.`;
    const ask = code
      ? `Could you confirm that tax code ${code} is the current one HMRC has issued for me?`
      : "Could you confirm which tax code HMRC has currently issued for me?";
    return [opening, ask, "Thanks."].join("\n\n");
  }

  // A message whose only concern is the tax code should not open by saying
  // the figures need checking: on an emergency code the figures can be
  // exactly right for the code that was applied, and the code is the thing
  // being questioned.
  const allAboutTheCode = kinds.length > 0 && kinds.every((kind) => kind === "code");

  const opening =
    `Hi,\n\nI’ve been looking at ${period} and I think ` +
    (allAboutTheCode
      ? "my tax code may need checking."
      : paragraphs.length === 1
        ? "one of the figures may need checking."
        : "a couple of the figures may need checking.");

  return [
    opening,
    ...paragraphs,
    request ?? "Could you take a look and let me know?",
    "Thanks.",
  ].join("\n\n");
}
