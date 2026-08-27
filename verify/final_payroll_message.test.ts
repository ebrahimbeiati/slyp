// Item 27: payrollMessage.ts against REAL API responses, plus gated variants.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildPayrollMessage } from "../lib/payrollMessage.ts";
import type { AnalysisResult } from "../app/Types/Types.ts";

const live = JSON.parse(readFileSync("verify/_live_results.json", "utf8")) as
  Record<string, AnalysisResult>;

const BAD = ["undefined", "£null", "null", "NaN", "£NaN", ": ,", "£undefined"];

function audit(label: string, msg: string) {
  console.log(`\n===== ${label} =====\n${msg}\n`);
  for (const b of BAD) {
    assert.ok(!msg.includes(b), `${label}: message contains ${JSON.stringify(b)}`);
  }
  for (const lineText of msg.split("\n")) {
    assert.ok(!/:\s*$/.test(lineText), `${label}: dangling fragment -> ${JSON.stringify(lineText)}`);
  }
}

for (const [key, result] of Object.entries(live)) {
  test(`live result: ${key}`, () => audit(key, buildPayrollMessage(result)));
}

test("the estimate is carried, and its branch survives the rewrite as prose", () => {
  // The message no longer prints the Estimate's label verbatim, so the
  // conditional/unconditional split has to survive as a sentence instead.
  // Getting this wrong would assert something the analysis deliberately
  // did not: that the figure applies regardless of other employment.
  const stated = buildPayrollMessage(live.emergency_only_job);
  const notTold = buildPayrollMessage(live.emergency_not_told);

  assert.ok(stated.includes("£419.00"), "stated branch lost the figure");
  assert.ok(notTold.includes("£419.00"), "conditional branch lost the figure");

  assert.match(stated, /As this has been my only employment this tax year/);
  assert.match(notTold, /If this has been my only employment this tax year/);
  assert.ok(
    !stated.includes("If this has been"),
    "the stated branch must not be hedged back into a conditional",
  );
});

test("the message reads as prose, not as a diagnostic dump", () => {
  for (const [label, result] of Object.entries(live)) {
    const msg = buildPayrollMessage(result);

    // No list markup, no decoration, no label-colon-value lines.
    for (const token of ["•", "→", "* ", "## ", "**"]) {
      assert.ok(!msg.includes(token), `${label}: contains ${JSON.stringify(token)}`);
    }
    for (const line of msg.split("\n")) {
      assert.ok(!/^\s*[-*]\s/.test(line), `${label}: bullet line -> ${line}`);
      assert.ok(
        !/^[A-Z][A-Za-z ]{2,28}: /.test(line),
        `${label}: label-colon-value line -> ${line}`,
      );
    }

    // No branding - the user sends this as themselves.
    assert.ok(!/via Slyp/i.test(msg), `${label}: still branded`);

    // Opens as a person, ends with a question and a sign-off.
    assert.ok(msg.startsWith("Hi,"), `${label}: does not open as a message`);
    assert.ok(msg.endsWith("Thanks."), `${label}: does not sign off`);
    const beforeThanks = msg.slice(0, -"Thanks.".length).trimEnd();
    assert.ok(
      beforeThanks.endsWith("?"),
      `${label}: does not end with a request -> ${beforeThanks.slice(-70)}`,
    );
  }
});

test("correlated differences are stated once, not twice", () => {
  // The dirty payslip carries a £41.00 tax variance AND a £41.00
  // reconciliation gap. Those are one discrepancy to a reader.
  const cases = JSON.parse(
    readFileSync("verify/_payroll_cases.json", "utf8"),
  ) as Record<string, AnalysisResult>;
  const dirty = cases["Dirty payslip (tax + reconciliation, both GBP 41.00)"];
  assert.ok(dirty, "dirty payslip case missing");

  const msg = buildPayrollMessage(dirty);
  const mentions = msg.split("£41.00").length - 1;
  assert.equal(mentions, 1, `£41.00 stated ${mentions} times, expected once`);
  assert.match(msg, /which would also account for/);
  // Hedged, never causal: the engine cannot prove the two are the same.
  assert.ok(!/because|caused by|due to/i.test(msg), "asserts a cause it cannot prove");
});

test("the tax code basis is always stated", () => {
  const cases = JSON.parse(
    readFileSync("verify/_payroll_cases.json", "utf8"),
  ) as Record<string, AnalysisResult>;
  for (const [label, result] of Object.entries(cases)) {
    const code = result.extract?.tax_code.value;
    if (!code || result.extract?.unreadable_fields.includes("tax_code.value")) continue;
    const msg = buildPayrollMessage(result);
    if (!msg.includes(code)) continue; // code not mentioned in this message
    assert.ok(
      /week 1 \/ month 1 basis|no week 1 or month 1 marking|current one HMRC has issued/.test(msg),
      `${label}: mentions the code without saying how it is applied`,
    );
  }
});

test("BR second job carries no estimate", () => {
  const msg = buildPayrollMessage(live.br_second_job);
  assert.ok(!/overpayment/i.test(msg), "a second job must never carry an estimate");
});

test("every gated field drops its clause cleanly", () => {
  const base = live.emergency_only_job;
  const gated: AnalysisResult = JSON.parse(JSON.stringify(base));
  gated.extract!.unreadable_fields = [
    "pay.gross_this_period", "deductions.income_tax",
    "deductions.national_insurance", "deductions.pension_employee",
    "net_pay", "tax_code.value",
  ];
  const msg = buildPayrollMessage(gated);
  audit("all fields gated", msg);
  assert.ok(!msg.includes("Gross pay"), "gated gross must not print");
  assert.ok(!msg.includes("Tax code:"), "gated tax code must not print");
});

test("null values drop their clause too", () => {
  const nulled: AnalysisResult = JSON.parse(JSON.stringify(live.emergency_only_job));
  nulled.extract!.pay.gross_this_period = null;
  nulled.extract!.net_pay = null;
  nulled.extract!.deductions.student_loan = null;
  const msg = buildPayrollMessage(nulled);
  audit("null values", msg);
});

test("a non-ok result says so rather than emitting a half message", () => {
  const bad: AnalysisResult = JSON.parse(JSON.stringify(live.emergency_only_job));
  bad.status = "unsupported";
  assert.equal(buildPayrollMessage(bad), "No payslip analysis is available to share.");
});

test("a finding whose estimate key is ABSENT (not null) does not crash", () => {
  const r: AnalysisResult = JSON.parse(JSON.stringify(live.emergency_only_job));
  for (const f of r.findings) delete (f as unknown as Record<string, unknown>).estimate;
  const msg = buildPayrollMessage(r);
  audit("estimate key absent", msg);
});
