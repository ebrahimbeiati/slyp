// Confirms the CLEAR-findings render split did not touch the copy-for-payroll
// message. payrollMessage.ts reads result.findings directly and knows nothing
// about the page's section grouping - this proves it behaviourally rather than
// by assertion.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildPayrollMessage } from "../lib/payrollMessage.ts";
import type { AnalysisResult } from "../app/Types/Types.ts";

const live = JSON.parse(readFileSync("verify/_render_results.json", "utf8")) as
  Record<string, AnalysisResult>;

for (const [label, result] of Object.entries(live)) {
  test(`payroll message — ${label}`, () => {
    const msg = buildPayrollMessage(result);
    const clear = result.findings.filter((f) => f.severity === "clear");
    const action = result.findings.filter((f) => f.severity === "action");
    const withEstimate = result.findings.filter((f) => f.estimate !== null);

    console.log(`\n===== ${label} =====`);
    console.log(`  findings: ${result.findings.map((f) => `${f.severity}:${f.id}`).join(", ") || "none"}`);
    console.log(`  -> "Things worth checking" section: ${action.length > 0 ? "yes" : "no"}`);
    console.log(`  -> estimate lines: ${withEstimate.length}`);
    console.log(msg.split("\n").map((l) => `     | ${l}`).join("\n"));

    // A CLEAR finding must never reach the message: it is neither "action"
    // nor estimate-bearing.
    for (const f of clear) {
      assert.ok(!msg.includes(f.title), `${label}: CLEAR title leaked -> ${f.title}`);
      assert.equal(f.estimate, null, `${label}: a CLEAR finding carries an estimate`);
    }
    // And nothing malformed.
    for (const bad of ["undefined", "£null", "NaN"]) {
      assert.ok(!msg.includes(bad), `${label}: contains ${bad}`);
    }
  });
}

test("the message is byte-identical to the pre-change capture", () => {
  const before = JSON.parse(readFileSync("verify/_live_results.json", "utf8")) as
    Record<string, AnalysisResult>;
  // br_second_job in the pre-change capture was only_job=false, same as
  // "BR £476, only_job=false" here.
  const a = buildPayrollMessage(before.br_second_job);
  const b = buildPayrollMessage(live["BR £476, only_job=false"]);
  assert.equal(a, b, "the BR second-job payroll message changed");

  const c = buildPayrollMessage(before.emergency_only_job);
  const d = buildPayrollMessage(live["emergency M1 mid-year start"]);
  assert.equal(c, d, "the emergency payroll message changed");
  console.log("\n  payroll output identical before and after the render split");
});
