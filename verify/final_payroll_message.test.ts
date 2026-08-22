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

test("estimate is carried, with its branch label intact", () => {
  const stated = buildPayrollMessage(live.emergency_only_job);
  const notTold = buildPayrollMessage(live.emergency_not_told);
  assert.match(stated, /Possible overpayment so far this tax year: £419\.00/);
  assert.match(notTold, /Possible overpayment, if this has been your only employment this tax year: £419\.00/);
  assert.ok(!stated.includes("if this has been"), "stated branch must not be hedged");
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
