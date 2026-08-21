// Run: npm test
//
// What actually goes on the wire. lib/onlyJob.test.ts pins the mapping in
// isolation; this pins that the mapped value survives all the way into
// the multipart body the API receives - including the case that has no
// value at all, where the field must be ABSENT rather than present-and-
// false. main.py reads it as {"true": True, "false": False}.get(raw),
// so a stray "false" is a positive assertion of a second job, not a
// neutral default.

import test from "node:test";
import assert from "node:assert/strict";

import { analysePayslip } from "./Api.ts";
import { onlyJobFromAnswer, type OtherJobAnswer } from "./onlyJob.ts";

/** Runs the client against a stubbed fetch and hands back the FormData
 * it tried to send. */
async function capturePost(answer: OtherJobAnswer | null): Promise<FormData> {
  let sent: FormData | undefined;
  const original = globalThis.fetch;

  globalThis.fetch = (async (_url: string, init: RequestInit) => {
    sent = init.body as FormData;
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;

  try {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "p.pdf", {
      type: "application/pdf",
    });
    await analysePayslip(file, onlyJobFromAnswer(answer));
  } finally {
    globalThis.fetch = original;
  }

  assert.ok(sent, "fetch was never called");
  return sent;
}

test("'no other job' sends only_job=true", async () => {
  const form = await capturePost("no");
  assert.equal(form.get("only_job"), "true");
});

test("'had another job' sends only_job=false", async () => {
  const form = await capturePost("yes");
  assert.equal(form.get("only_job"), "false");
});

test("'not sure' omits only_job from the body entirely", async () => {
  const form = await capturePost("not_sure");
  assert.equal(form.has("only_job"), false);
  assert.equal(form.get("only_job"), null);
});

test("an unanswered question omits it too", async () => {
  const form = await capturePost(null);
  assert.equal(form.has("only_job"), false);
});

test("the payslip file is always sent", async () => {
  const form = await capturePost("no");
  assert.ok(form.get("file") instanceof File);
});

test("no job_label or other user metadata is ever added to the body", async () => {
  // job_label does not exist anywhere in this codebase. Pinned so that if
  // it is ever added, it is added deliberately - and never to the
  // extraction payload, which is built server-side from the PDF text
  // alone (slyp/extraction.py financial_lines_only).
  const form = await capturePost("no");
  assert.deepEqual([...form.keys()].sort(), ["file", "only_job"]);
});
