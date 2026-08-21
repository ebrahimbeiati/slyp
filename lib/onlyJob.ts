// The upload question and its mapping to the API's `only_job` field.
//
// THE MAPPING IS INVERTED, DELIBERATELY. The question asks about OTHER
// jobs; the API field records whether this is the ONLY job. So:
//
//     "Yes, I've had another job"   ->  only_job = false
//     "No, no other job"            ->  only_job = true
//     "Not sure"                    ->  omitted entirely
//
// Answering YES to the question means only_job = FALSE. Getting this
// backwards would silently invert every finding that depends on it -
// a BR code would read as normal for someone whose allowance should be
// here, and the emergency-code overpayment estimate would be stated
// firmly for exactly the people it does not apply to. Hence
// onlyJobFromAnswer() rather than a boolean flipped inline at the call
// site, and hence lib/onlyJob.test.ts.
//
// Why the question changed from "Is this your only job?": the estimate's
// arithmetic needs no OTHER EMPLOYMENT THIS TAX YEAR, which is not the
// same as no other job right now. Someone who changed jobs in July - the
// most common reason to be on a W1/M1 code at all - would truthfully
// answer "yes, this is my only job" while their previous employer had
// already used part of the allowance the estimate assumes is unused. See
// slyp/findings.py _emergency_basis_finding().

export type OtherJobAnswer = "yes" | "no" | "not_sure";

/** null means "don't send the field at all" - findings that depend on it
 * stay conditional. That is a distinct outcome from `false`, which
 * asserts a second job, so "not sure" must never collapse into "no". */
export function onlyJobFromAnswer(answer: OtherJobAnswer | null): boolean | null {
  switch (answer) {
    case "yes":
      return false; // had another job -> this is not the only one
    case "no":
      return true; // no other job -> this is the only one
    default:
      return null; // "not sure", or not answered yet
  }
}

/** UK tax years run 6 April to 5 April. The 6 April on or before `on`. */
export function taxYearStart(on: Date): Date {
  const boundary = new Date(on.getFullYear(), 3, 6); // month 3 = April
  return on >= boundary
    ? boundary
    : new Date(on.getFullYear() - 1, 3, 6);
}

/**
 * "6 April 2026 to 5 April 2027" - shown under the question so "this tax
 * year" is never assumed knowledge. Built from explicit parts rather than
 * toLocaleDateString so it reads the same in every locale the browser
 * might be set to.
 */
export function taxYearRangeLabel(on: Date): string {
  const start = taxYearStart(on);
  return `6 April ${start.getFullYear()} to 5 April ${start.getFullYear() + 1}`;
}
