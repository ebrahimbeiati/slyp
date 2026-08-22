"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
import type { AnalysisResult, Finding, PayslipExtract, Score, Severity } from "@/app/Types/Types";
import { buildPayrollMessage } from "@/lib/payrollMessage";
import { decodeStoredResult, STORAGE_KEY } from "@/lib/storedResult";

/** Format a Decimal-as-string field for display. Never used to derive a
 * new figure - only to add thousands separators / a £ prefix to a number
 * the backend already computed. */
function gbp(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `£${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Purely cosmetic: a bar-chart width as a percentage of gross. Not a
 * figure shown to the user - the actual pound amounts always come
 * straight from the API's string values via gbp() above. */
function pctOfGross(part: string | null, gross: string | null): number {
  const p = part ? Number(part) : 0;
  const g = gross ? Number(gross) : 0;
  if (!Number.isFinite(p) || !Number.isFinite(g) || g <= 0) return 0;
  return Math.min(Math.round((p / g) * 100), 100);
}

const SEVERITY_ORDER: Record<Severity, number> = { action: 0, advisory: 1, clear: 2 };

const SEVERITY_STYLES: Record<Severity, { badge: string; border: string }> = {
  action: { badge: "bg-[#2E201B] border-[#4D2E24] text-[#FF9466]", border: "border-[#4D2E24]" },
  advisory: { badge: "bg-[#2a1f0e] border-[#4d3a1a] text-[#FFAE34]", border: "border-[#4d3a1a]" },
  clear: { badge: "bg-[#1C2C24] border-[#2B473A] text-[var(--ink)]", border: "border-[var(--border)]" },
};

/** Renders a money field with the confidence-gate state made explicit:
 * a field the backend couldn't read confidently is never blank space or
 * a silent zero - it says so. */
function GatedMoney({
  extract,
  field,
  value,
}: {
  extract: PayslipExtract;
  field: string;
  value: string | null;
}) {
  if (extract.unreadable_fields.includes(field)) {
    return <span className="text-[var(--sage)] opacity-70 italic text-[0.9em]">Could not be read</span>;
  }
  if (value === null) {
    return <span className="text-[var(--sage)] opacity-50">—</span>;
  }
  return <>{gbp(value)}</>;
}

function FindingCard({ finding }: { finding: Finding }) {
  const style = SEVERITY_STYLES[finding.severity];
  return (
    <div className={`w-full bg-[var(--surface-2)] border ${style.border} rounded-2xl p-4 mb-3`}>
      <div className="flex items-start gap-3">
        <div
          className={`shrink-0 px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border ${style.badge}`}
        >
          {finding.severity}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-[var(--ink)] text-xs font-bold leading-tight mb-1">{finding.title}</h3>
          <p className="text-[var(--sage)] text-[10px] leading-relaxed">{finding.explanation}</p>
          {finding.estimate && (
            <div className="mt-2 text-[11px] font-bold text-[var(--ink)]">
              {finding.estimate.label}: {gbp(finding.estimate.amount_gbp)}
            </div>
          )}
          {finding.next_step && (
            <p className="text-[var(--sage)] text-[10px] mt-2 opacity-80">→ {finding.next_step}</p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * What was checked, what wasn't, and why - in that order.
 *
 * A check that had nothing to compare is listed here as not applicable
 * rather than counted as a pass. "4/4 checks clear" on a payslip under
 * every threshold was four comparisons of £0.00 against £0.00, and on a
 * payslip whose calculation never ran it was four absences of a finding.
 * Both read as confidence the analysis had not earned.
 */
function WhatWeChecked({ score }: { score: Score }) {
  // Defaulted, despite the type saying these are always present: this
  // component renders a result rehydrated from localStorage, which can
  // have been written by an older build of the app. The hydration does
  // `JSON.parse(raw) as AnalysisResult` - an unchecked cast - so the type
  // describes what the API sends today, not what is actually on disk.
  // not_applicable was added after some results were already saved, and
  // reading .length off it crashed the whole page rather than degrading.
  const notApplicable = score.not_applicable ?? [];
  const movers = score.movers ?? [];
  const total = score.checks_run + notApplicable.length;

  return (
    <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl p-4 mb-4">
      <div className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium mb-2">
        What we checked
      </div>

      <p className="text-[var(--ink)] text-[11px] leading-relaxed">
        {score.checks_run === 0
          ? "No check could be completed on this payslip."
          : `${score.checks_passed} of ${score.checks_run} ${
              score.checks_run === 1 ? "check" : "checks"
            } passed${total > score.checks_run ? ` (of ${total} we look at)` : ""}.`}
      </p>

      {notApplicable.length > 0 && (
        <ul className="mt-2 space-y-1">
          {notApplicable.map((reason) => (
            <li key={reason} className="text-[var(--sage)] text-[10px] leading-relaxed">
              • {reason}
            </li>
          ))}
        </ul>
      )}

      {movers.length > 0 && (
        <ul className="mt-2 space-y-1">
          {movers.map((mover) => (
            <li key={mover} className="text-[var(--sage)] text-[10px] leading-relaxed">
              → {mover}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function HomePage() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [showHomeWarning, setShowHomeWarning] = useState(false);
  const [copyLabel, setCopyLabel] = useState("Copy for payroll");
  // Set when we found a saved result this build cannot trust. Shown
  // instead of the empty state, so a discarded result is visible rather
  // than looking like "you never uploaded anything".
  const [discarded, setDiscarded] = useState(false);

  useEffect(() => {
    const loaded = decodeStoredResult(localStorage.getItem(STORAGE_KEY));

    if (loaded.kind === "ok") {
      setResult(loaded.result);
      return;
    }

    if (loaded.kind === "outdated" || loaded.kind === "unreadable") {
      // Remove it now. It can never be rendered by this build, and
      // leaving it would mean re-deciding this on every page load.
      localStorage.removeItem(STORAGE_KEY);
      setDiscarded(true);
    }
  }, []);

  const hasData = result !== null;

  const wipeAndReset = () => {
    localStorage.removeItem(STORAGE_KEY);
    setResult(null);
    setDiscarded(false);
    setShowHomeWarning(false);
  };

  const handleCopyToPayroll = async () => {
    if (!result) return;
    const message = buildPayrollMessage(result);
    try {
      await navigator.clipboard.writeText(message);
      setCopyLabel("Copied");
    } catch {
      setCopyLabel("Couldn't copy");
    }
    setTimeout(() => setCopyLabel("Copy for payroll"), 2000);
  };

  return (
    <PrototypeScaffold step={hasData ? 1 : 0} nextHref="/upload">
      {() => (
        <div className="basis-screen active relative pb-14 h-full flex flex-col justify-between text-[var(--ink)] font-sans select-none">
            {/* ── Empty state ── */}
            {!hasData ? (
              <div className="flex flex-col flex-1 animate-fadeIn">
                <div className="flex justify-between items-center mb-6 mt-2 shrink-0">
                  <div className="text-left">
                    <div className="text-gray-400 text-xs font-normal tracking-wide">Welcome</div>
                    <div className="text-white text-xl font-bold tracking-tight mt-0.5">
                      <span className="inline-block animate-wave transform-gpu origin-[70%_70%]">👋</span>
                    </div>
                  </div>
                </div>

                {/* A discarded result is said out loud. Silently showing
                    the empty state would read as "you never uploaded
                    anything", when what actually happened is that we
                    threw away a result we could no longer trust. */}
                {discarded && (
                  <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-2xl px-4 py-3 mb-5 text-left">
                    <div className="text-[#FFAE34] text-[10px] font-bold uppercase tracking-wider mb-1">
                      Saved result cleared
                    </div>
                    <p className="text-[var(--sage)] text-[11px] leading-relaxed">
                      That result was from an earlier version of Slyp, so we
                      cleared it rather than show you figures this version
                      didn&apos;t work out. Please upload your payslip again.
                    </p>
                  </div>
                )}

                <div className="w-full bg-[#34423d] border border-[#515a57] rounded-3xl p-5 mb-5 flex flex-col items-start text-left shadow-md">
                  <div className="w-9 h-9 rounded-xl bg-[#1A2A24] border border-[#2D453E] flex items-center justify-center mb-4">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FFAE34" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" />
                      <line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                  </div>
                  <h2 className="text-white text-base font-bold tracking-tight mb-1.5">Add your first payslip</h2>
                  <p className="text-gray-400 text-[11px] leading-relaxed mb-6 font-normal">
                    Takes about 20 seconds. We read the numbers, then forget the file.
                  </p>
                  <Link
                    href="/upload"
                    className="w-full py-3 bg-[#FFAE34] hover:bg-[#E59A2B] text-black text-xs font-bold rounded-xl transition-all border-0 shadow-sm uppercase tracking-wider cursor-pointer active:scale-[0.99] text-center block"
                  >
                    Scan payslip
                  </Link>
                </div>
              </div>
            ) : result!.status !== "ok" ? (
              /* ── Could not analyse this payslip ── */
              <div className="flex flex-col flex-1 animate-fadeIn">
                <div className="flex justify-between items-center w-full my-4 shrink-0">
                  <Link href="/upload" className="text-[var(--sage)] text-base font-bold hover:text-[var(--ink)] transition-colors">
                    ‹
                  </Link>
                  <h1 className="text-[var(--ink)] text-xs font-bold uppercase tracking-widest">Result</h1>
                  <button
                    type="button"
                    onClick={() => setShowHomeWarning(true)}
                    className="text-red-500 border-0 bg-transparent text-[9px] uppercase cursor-pointer hover:underline"
                  >
                    Wipe
                  </button>
                </div>

                <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-2xl p-5 flex flex-col items-start text-left">
                  <div className="text-[#FFAE34] text-xs font-bold uppercase tracking-wider mb-2">
                    {result!.verdict?.headline ?? "We couldn't check this payslip"}
                  </div>
                  <p className="text-[var(--sage)] text-[11px] leading-relaxed mb-5">
                    {result!.failure_reason ?? "Please try a different file or a clearer scan."}
                  </p>
                  <Link
                    href="/upload"
                    className="w-full py-2.5 bg-[#FFAE34] text-black text-xs font-bold rounded-xl text-center uppercase tracking-wider"
                  >
                    Try another payslip
                  </Link>
                </div>
              </div>
            ) : (
              /* ── Dashboard ── */
              <div className="flex flex-col flex-1 overflow-y-auto custom-scrollbar pr-1">
                {(() => {
                  const extract = result!.extract!;
                  const gross = extract.pay.gross_this_period;
                  const net = extract.net_pay;
                  const tax = extract.deductions.income_tax;
                  const ni = extract.deductions.national_insurance;
                  const pension = extract.deductions.pension_employee;
                  const taxCode = extract.tax_code.value;

                  const taxPct = pctOfGross(tax, gross);
                  const niPct = pctOfGross(ni, gross);
                  const pensionPct = pctOfGross(pension, gross);

                  const sortedFindings = [...result!.findings].sort(
                    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
                  );

                  return (
                    <>
                      {/* Header */}
                      <div className="flex justify-between items-center w-full my-4 shrink-0">
                        <Link href="/upload" className="text-[var(--sage)] text-base font-bold hover:text-[var(--ink)] transition-colors">
                          ‹
                        </Link>
                        <h1 className="text-[var(--ink)] text-xs font-bold uppercase tracking-widest flex items-center gap-1.5">
                          <span className="inline-block animate-wave transform-gpu origin-[70%_70%]">👋</span> Welcome
                        </h1>
                        <button
                          type="button"
                          onClick={() => setShowHomeWarning(true)}
                          className="text-red-500 border-0 bg-transparent text-[9px] uppercase cursor-pointer hover:underline"
                        >
                          Wipe
                        </button>
                      </div>

                      {/* Net pay hero */}
                      <div className="mb-5 flex flex-col items-start w-full">
                        <span className="text-[var(--sage)] text-[10px] uppercase tracking-wider mb-1">
                          Net Pay{extract.period.tax_year ? ` · ${extract.period.tax_year}` : ""}
                        </span>
                        <div
                          className="text-[var(--ink)] text-3xl font-bold tracking-tight mb-1"
                          style={{ textShadow: "0 0 8px var(--border)" }}
                        >
                          <GatedMoney extract={extract} field="net_pay" value={net} />
                        </div>
                        <div className="text-[var(--sage)] text-[11px]">
                          of{" "}
                          <span className="text-[var(--ink)] font-bold">
                            <GatedMoney extract={extract} field="pay.gross_this_period" value={gross} />
                          </span>{" "}
                          gross
                          {taxCode && (
                            <>
                              {" "}
                              · <span className="text-[var(--ink)] font-bold">{taxCode}</span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Breakdown bar */}
                      <div className="w-full mb-3">
                        <div className="w-full h-2.5 bg-[var(--surface-2)] border border-[var(--border)] rounded-full overflow-hidden flex">
                          <div className="h-full bg-[#FF9466] transition-all" style={{ width: `${taxPct}%` }} title="Tax" />
                          <div className="h-full bg-[#5C7569] transition-all" style={{ width: `${niPct}%` }} title="NI" />
                          {pensionPct > 0 && (
                            <div className="h-full bg-[#2A3E34] transition-all" style={{ width: `${pensionPct}%` }} title="Pension" />
                          )}
                          <div className="h-full bg-[var(--ink)] flex-1 shadow-[0_0_8px_var(--ink)]" title="Net" />
                        </div>
                      </div>

                      {/* Legend */}
                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-[var(--sage)] mb-6">
                        <span className="flex items-center gap-1">
                          <span className="w-1 h-1 rounded-full bg-[#FF9466]" />
                          Tax <GatedMoney extract={extract} field="deductions.income_tax" value={tax} />
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="w-1 h-1 rounded-full bg-[#5C7569]" />
                          NI <GatedMoney extract={extract} field="deductions.national_insurance" value={ni} />
                        </span>
                        {pension !== null && (
                          <span className="flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-[#2A3E34]" />
                            Pension <GatedMoney extract={extract} field="deductions.pension_employee" value={pension} />
                          </span>
                        )}
                        <span className="flex items-center gap-1 text-[var(--ink)] font-bold">
                          <span className="w-1 h-1 rounded-full bg-[var(--ink)]" />
                          Net <GatedMoney extract={extract} field="net_pay" value={net} />
                        </span>
                      </div>

                      {/* Verdict + score */}
                      {result!.verdict && (
                        <div
                          className={`w-full rounded-2xl p-4 mb-4 border ${
                            SEVERITY_STYLES[result!.verdict.severity].border
                          } bg-[var(--surface-2)]`}
                        >
                          {/* One statement, not two. The findings count and
                              the checks-clear count are different kinds of
                              thing - "1 thing worth checking" beside
                              "4/4 checks clear" reads as a contradiction
                              even when both are true. What was and wasn't
                              checked now sits below the findings, in
                              WhatWeChecked. */}
                          <span className="text-[var(--ink)] text-xs font-bold">{result!.verdict.headline}</span>
                        </div>
                      )}

                      {/* Findings */}
                      {sortedFindings.length > 0 && (
                        <div className="w-full mb-4">
                          <div className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium mb-2">
                            What we found
                          </div>
                          {sortedFindings.map((finding) => (
                            <FindingCard key={finding.id} finding={finding} />
                          ))}
                        </div>
                      )}

                      {/* What was actually checked. Sits below the
                          findings deliberately: it is detail, not a
                          headline, and pairing it with the verdict up top
                          was what made "1 thing worth checking" read as a
                          contradiction of "4/4 checks clear". */}
                      {result!.score && <WhatWeChecked score={result!.score} />}

                      {/* Fields that couldn't be read */}
                      {extract.unreadable_fields.length > 0 && (
                        <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl p-4 mb-4">
                          <div className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium mb-2">
                            Couldn&apos;t read confidently
                          </div>
                          <p className="text-[var(--sage)] text-[10px] leading-relaxed">
                            {extract.unreadable_fields.join(", ")} — nothing was guessed for these; any check that
                            depends on them was skipped rather than estimated.
                          </p>
                        </div>
                      )}

                      {/* Copy to payroll */}
                      <button
                        type="button"
                        onClick={handleCopyToPayroll}
                        className="w-full py-3 mb-4 bg-[var(--surface-2)] border border-[var(--border)] text-[var(--ink)] text-xs font-bold rounded-xl uppercase tracking-wider hover:border-[#FFAE34]/40 transition-colors cursor-pointer"
                      >
                        {copyLabel}
                      </button>
                    </>
                  );
                })()}
              </div>
            )}

            {/* ── Bottom nav ── */}
            <div className="basis-bottom-nav flex justify-center items-center gap-16 border-t border-[var(--border)] pt-4 mt-auto shrink-0 w-full relative z-20">
              <button
                type="button"
                onClick={() => {
                  if (hasData) setShowHomeWarning(true);
                }}
                className="text-[var(--amber)] text-xs flex flex-col items-center gap-1 font-bold cursor-pointer border-0 bg-transparent focus:outline-none"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#FFAE34]" />
                Home
              </button>
            </div>

            {/* ── Sheet backdrop ── */}
            <button
              type="button"
              className={`fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity duration-300 z-40 ${sheetOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
              onClick={() => setSheetOpen(false)}
              aria-label="Close menu"
            />

            {/* ── Wipe warning modal ── */}
            {showHomeWarning && (
              <div className="absolute inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center p-5 z-50 animate-fadeIn">
                <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl p-5 flex flex-col text-left font-mono">
                  <div className="text-[var(--amber)] text-sm font-bold uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    ⚠️ Clear data?
                  </div>
                  <p className="text-[var(--ink)] text-xs leading-relaxed font-normal mb-6">
                    This will remove the saved payslip result from this device. You&apos;ll need to scan it again.
                  </p>
                  <div className="flex flex-col gap-2">
                    <button
                      type="button"
                      onClick={wipeAndReset}
                      className="w-full py-2.5 bg-[#FFAE34] hover:bg-[#E59A2B] text-black font-bold rounded-xl text-[11px] uppercase tracking-wider border-0 cursor-pointer transition-colors"
                    >
                      Yes, clear everything
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowHomeWarning(false)}
                      className="w-full py-2.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--sage)] hover:text-[var(--ink)] font-semibold rounded-xl text-[11px] uppercase tracking-wider cursor-pointer transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}

          </div>
      )}
    </PrototypeScaffold>
  );
}
