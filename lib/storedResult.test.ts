// Run: npm test
//
// The case this file exists for: a result saved by an earlier build must
// be DISCARDED, not defaulted into something renderable. Defaulting is
// what turned a crash into "4 of 4 checks passed" with no reasons - a
// stale score presented as if this build had computed it.

import test from "node:test";
import assert from "node:assert/strict";

import {
  decodeStoredResult,
  encodeStoredResult,
  RESULT_SCHEMA_VERSION,
} from "./storedResult.ts";

/** Shaped like a real pre-versioning payload: a complete-looking
 * AnalysisResult whose Score predates not_applicable. This is exactly
 * what is sitting in the demo browser right now. */
const LEGACY_UNVERSIONED = JSON.stringify({
  status: "ok",
  findings: [],
  score: { value: 100, checks_passed: 4, checks_run: 4, movers: [] },
  extract: { unreadable_fields: [] },
});

test("a payload with no schema_version is discarded, not defaulted", () => {
  const loaded = decodeStoredResult(LEGACY_UNVERSIONED);

  assert.equal(loaded.kind, "outdated");
  // and specifically: nothing renderable comes back
  assert.equal("result" in loaded, false);
});

test("a payload from a different schema version is discarded", () => {
  const raw = JSON.stringify({
    schema_version: RESULT_SCHEMA_VERSION + 1,
    saved_at: new Date().toISOString(),
    result: { status: "ok", findings: [], score: null },
  });

  assert.equal(decodeStoredResult(raw).kind, "outdated");
});

test("a payload from this build round-trips and is rendered", () => {
  const result = {
    status: "ok",
    findings: [],
    score: { value: 100, checks_passed: 2, checks_run: 2, movers: [], not_applicable: ["x"] },
  };

  const loaded = decodeStoredResult(encodeStoredResult(result as never));

  assert.equal(loaded.kind, "ok");
  assert.deepEqual(loaded.kind === "ok" ? loaded.result : null, result);
});

test("the envelope carries the current version and a timestamp", () => {
  const envelope = JSON.parse(encodeStoredResult({ status: "ok" } as never));

  assert.equal(envelope.schema_version, RESULT_SCHEMA_VERSION);
  assert.ok(!Number.isNaN(Date.parse(envelope.saved_at)));
});

test("nothing saved reads as empty, not as an error", () => {
  assert.equal(decodeStoredResult(null).kind, "empty");
  assert.equal(decodeStoredResult("").kind, "empty");
});

test("corrupt or non-object storage is discarded without throwing", () => {
  assert.equal(decodeStoredResult("{not json").kind, "unreadable");
  assert.equal(decodeStoredResult('"a string"').kind, "unreadable");
  assert.equal(decodeStoredResult("null").kind, "unreadable");
  assert.equal(
    decodeStoredResult(JSON.stringify({ schema_version: RESULT_SCHEMA_VERSION })).kind,
    "unreadable",
  );
});

test("the version check does not inspect the body to decide", () => {
  // A legacy payload that happens to carry a not_applicable field is
  // still legacy. Deciding from the body is one step from defaulting.
  const raw = JSON.stringify({
    status: "ok",
    findings: [],
    score: { value: 100, checks_passed: 2, checks_run: 2, movers: [], not_applicable: [] },
  });

  assert.equal(decodeStoredResult(raw).kind, "outdated");
});
