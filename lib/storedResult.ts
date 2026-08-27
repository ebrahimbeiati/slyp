// The one place an AnalysisResult is written to or read from
// localStorage.
//
// Why this exists: the page used to do `JSON.parse(raw) as
// AnalysisResult`, an unchecked cast. When Score gained a
// not_applicable field, every result already saved by an earlier build
// became a payload whose shape the type lied about - and the page
// crashed reading .length off a field that wasn't there. Defaulting the
// missing field stopped the crash and replaced it with something worse:
// the stale result rendered as "4 of 4 checks passed" with no reasons,
// a confident score computed by scoring rules that no longer exist.
//
// A stale result must therefore be DISCARDED, never patched up to look
// current. Rendering an old score as if this build produced it is the
// exact failure the product exists to avoid, pointed at ourselves.

import type { AnalysisResult } from "@/app/Types/Types";

export const STORAGE_KEY = "slyp:latest";

// BUMP THIS whenever the shape of AnalysisResult changes in a way that
// would make an older stored payload render wrongly - a new field the UI
// reads, a changed meaning for an existing one, different scoring rules
// behind the same numbers. Bumping costs a user one re-upload. Not
// bumping shows them a stale figure and says nothing.
//
// 1: first versioned shape. Everything written before this (no
//    schema_version key at all) is from an unversioned build and is
//    discarded on sight.
export const RESULT_SCHEMA_VERSION = 1;

type StoredEnvelope = {
  schema_version: number;
  saved_at: string;
  result: AnalysisResult;
};

export type LoadedResult =
  /** Nothing saved. */
  | { kind: "empty" }
  /** Saved by this build; safe to render. */
  | { kind: "ok"; result: AnalysisResult }
  /** Saved by an earlier build. Must not be rendered. */
  | { kind: "outdated" }
  /** Not JSON, or not the shape we write. Also must not be rendered. */
  | { kind: "unreadable" };

export function encodeStoredResult(result: AnalysisResult): string {
  const envelope: StoredEnvelope = {
    schema_version: RESULT_SCHEMA_VERSION,
    saved_at: new Date().toISOString(),
    result,
  };
  return JSON.stringify(envelope);
}

/**
 * Never throws, and never returns a partially-trusted result. Anything
 * this function is not certain about comes back as "outdated" or
 * "unreadable", both of which the caller must treat as "there is nothing
 * to show" - not as an empty-but-valid analysis.
 */
export function decodeStoredResult(raw: string | null): LoadedResult {
  if (raw === null || raw === "") return { kind: "empty" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { kind: "unreadable" };
  }

  if (typeof parsed !== "object" || parsed === null) {
    return { kind: "unreadable" };
  }

  const envelope = parsed as Partial<StoredEnvelope>;

  // A payload with no schema_version at all is from an unversioned build.
  // This is the case that matters most in practice - it is what every
  // result saved before today looks like - and it must be discarded on
  // the missing key alone, without inspecting the body. Anything that
  // reads the body to decide is one step from defaulting it back in.
  if (envelope.schema_version !== RESULT_SCHEMA_VERSION) {
    return { kind: "outdated" };
  }

  if (typeof envelope.result !== "object" || envelope.result === null) {
    return { kind: "unreadable" };
  }

  return { kind: "ok", result: envelope.result as AnalysisResult };
}
