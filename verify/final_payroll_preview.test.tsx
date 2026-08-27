/**
 * The panel shows exactly what the clipboard gets.
 *
 * Server-renders PayrollPreviewPanel and compares the text content of the
 * message element to buildPayrollMessage() byte-for-byte, including line
 * breaks. This is the check behind the claim that what is on screen and
 * what lands in the paste are the same string.
 */
// Imports are extensionless because this file is COMPILED by tsc before it
// runs (see verify/tsconfig.preview.json) rather than type-stripped by node
// - node's --experimental-strip-types removes types but does not transform
// JSX, and both this test and the component under test contain JSX.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { PayrollPreviewPanel } from "../components/PayrollPreview";
import { buildPayrollMessage } from "../lib/payrollMessage";
import type { AnalysisResult } from "../app/Types/Types";

const cases = JSON.parse(readFileSync("verify/_payroll_cases.json", "utf8")) as
  Record<string, AnalysisResult>;

/** Pull the message element's text back out of the rendered HTML and undo
 *  the entity escaping, so we are comparing the characters a user would
 *  select and copy. */
function renderedMessage(html: string): string {
  const match = html.match(/<div class="whitespace-pre-wrap[^"]*">([\s\S]*?)<\/div>/);
  assert.ok(match, "could not find the message element in the rendered markup");
  return match[1]
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

// The two most likely to be on stage, named so a failure says which.
const ON_STAGE = [
  "Emergency M1 mid-year start",
  "Dirty payslip (tax + reconciliation, both GBP 41.00)",
];

for (const label of ON_STAGE) {
  test(`what is shown is what is copied — ${label}`, () => {
    const result = cases[label];
    assert.ok(result, `missing case: ${label}`);

    const message = buildPayrollMessage(result);
    const html = renderToStaticMarkup(
      <PayrollPreviewPanel message={message} onClose={() => {}} />,
    );
    const shown = renderedMessage(html);

    assert.equal(shown, message, "rendered text differs from the copied string");
    assert.equal(
      shown.length,
      message.length,
      `length differs: shown ${shown.length}, copied ${message.length}`,
    );
    // The blank lines between paragraphs are the thing most likely to be
    // lost in rendering, so assert them specifically.
    assert.ok(message.includes("\n\n"), "message has no paragraph breaks to preserve");
    assert.equal(
      (shown.match(/\n\n/g) ?? []).length,
      (message.match(/\n\n/g) ?? []).length,
      "paragraph breaks lost between clipboard and screen",
    );
    console.log(`\n  ${label}: ${message.length} chars, ` +
      `${(message.match(/\n/g) ?? []).length} line breaks, identical`);
  });
}

test("every case round-trips, not just the two demo ones", () => {
  for (const [label, result] of Object.entries(cases)) {
    const message = buildPayrollMessage(result);
    const html = renderToStaticMarkup(
      <PayrollPreviewPanel message={message} onClose={() => {}} />,
    );
    assert.equal(renderedMessage(html), message, `${label} differs`);
  }
});

test("the message is one text node, not per-line elements", () => {
  // A <br>-per-line or line-mapped render would look right and copy wrong.
  const message = buildPayrollMessage(cases["Emergency M1 mid-year start"]);
  const html = renderToStaticMarkup(
    <PayrollPreviewPanel message={message} onClose={() => {}} />,
  );
  const block = html.match(/<div class="whitespace-pre-wrap[^"]*">([\s\S]*?)<\/div>/)![1];
  assert.ok(!/<br\s*\/?>/i.test(block), "line breaks rendered as <br>, which copies differently");
  assert.ok(!/<\/?p[\s>]/i.test(block), "paragraphs split into elements");
  assert.ok(!/<!--/.test(block), "message split across multiple children");
});

test("the panel is a viewport overlay, not a card inside the phone frame", () => {
  const html = renderToStaticMarkup(
    <PayrollPreviewPanel message="Hi,\n\nThanks." onClose={() => {}} />,
  );
  assert.match(html, /class="fixed inset-0/, "not fixed to the viewport");
  assert.match(html, /role="dialog"/);
  assert.match(html, /aria-modal="true"/);
  assert.match(html, /aria-label="Close"/, "no close control");
});
