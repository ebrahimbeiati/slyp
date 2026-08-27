import { readFileSync } from "node:fs";
import { buildPayrollMessage } from "../lib/payrollMessage.ts";
import type { AnalysisResult } from "../app/Types/Types.ts";

const cases = JSON.parse(readFileSync("verify/_payroll_cases.json", "utf8")) as
  Record<string, AnalysisResult>;

for (const [label, result] of Object.entries(cases)) {
  const msg = buildPayrollMessage(result);
  const ids = result.findings.map((f) => `${f.severity}:${f.id}`).join(", ") || "no findings";
  console.log("\n" + "=".repeat(72));
  console.log(label);
  console.log("  (" + ids + ")");
  console.log("=".repeat(72));
  console.log(msg);

  const bad = ["undefined", "£null", "NaN", "•", "- ", " -> ", "→", "**", "##"];
  const found = bad.filter((b) => msg.includes(b));
  if (found.length) console.log(`\n  !! decorative/broken tokens present: ${found.join(" ")}`);
}
