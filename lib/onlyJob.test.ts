// Run: npm test        (node's built-in runner, no new dependency)
//
// Pins the inverted mapping between the upload question and the API's
// only_job field. See lib/onlyJob.ts for why this is worth a test of its
// own: the question and the field are opposites, and an inversion here
// would be silent - every branch would still render, just for the wrong
// person.

import test from "node:test";
import assert from "node:assert/strict";

import { onlyJobFromAnswer, taxYearStart, taxYearRangeLabel } from "./onlyJob.ts";

test("answering YES to 'any other job' means only_job = false", () => {
  assert.equal(onlyJobFromAnswer("yes"), false);
});

test("answering NO to 'any other job' means only_job = true", () => {
  assert.equal(onlyJobFromAnswer("no"), true);
});

test("'not sure' omits the field entirely - never false", () => {
  assert.equal(onlyJobFromAnswer("not_sure"), null);
  // The distinction that matters: "not sure" must not collapse into
  // "no other job", nor into "has another job".
  assert.notEqual(onlyJobFromAnswer("not_sure"), false);
  assert.notEqual(onlyJobFromAnswer("not_sure"), true);
});

test("unanswered behaves as 'not sure'", () => {
  assert.equal(onlyJobFromAnswer(null), null);
});

test("the three answers map to three distinct outcomes", () => {
  const outcomes = (["yes", "no", "not_sure"] as const).map(onlyJobFromAnswer);
  assert.deepEqual(outcomes, [false, true, null]);
  assert.equal(new Set(outcomes).size, 3);
});

test("tax year starts on 6 April", () => {
  // 5 April is still the previous tax year; 6 April starts the new one.
  assert.deepEqual(taxYearStart(new Date(2026, 3, 5)), new Date(2025, 3, 6));
  assert.deepEqual(taxYearStart(new Date(2026, 3, 6)), new Date(2026, 3, 6));
  assert.deepEqual(taxYearStart(new Date(2026, 7, 21)), new Date(2026, 3, 6));
  assert.deepEqual(taxYearStart(new Date(2027, 0, 31)), new Date(2026, 3, 6));
});

test("the range label names both boundary dates", () => {
  assert.equal(taxYearRangeLabel(new Date(2026, 7, 21)), "6 April 2026 to 5 April 2027");
  assert.equal(taxYearRangeLabel(new Date(2026, 3, 5)), "6 April 2025 to 5 April 2026");
});
