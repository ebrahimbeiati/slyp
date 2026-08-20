"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AskSheet } from "@/components/prototype/AskSheet";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
import type { Payslip } from "@/app/Types/Types";

const STORAGE_KEY = "slyp:payslips";

/** Format a number as £1,234 (no decimals for whole pounds, 2dp otherwise) */
function fmt(n: number): string {
  return Number.isInteger(n)
    ? n.toLocaleString("en-GB")
    : n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Format as £n — prefix included */
function gbp(n: number): string {
  return `£${fmt(n)}`;
}

export default function HomePage() {
  const [payslip, setPayslip] = useState<Payslip | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [bracketExpanded, setBracketExpanded] = useState(false);
  const [partTimeExpanded, setPartTimeExpanded] = useState(false);
  const [showHomeWarning, setShowHomeWarning] = useState(false);
  const [premiumFeature, setPremiumFeature] = useState<string | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const list: Payslip[] = JSON.parse(raw);
      if (list.length > 0) setPayslip(list[list.length - 1]);
    } catch (err) {
      console.error("Failed to read payslips from storage:", err);
    }
  }, []);

  const hasData = payslip !== null;

  // ── Derived values (all from flat Payslip, all monthly) ─────────────────
  const gross        = payslip?.grossPay           ?? 0;
  const net          = payslip?.netPay             ?? 0;
  const incomeTax    = payslip?.incomeTax          ?? 0;
  const ni           = payslip?.nationalInsurance  ?? 0;
  const pension      = payslip?.pensionContribution ?? 0;
  const hourlyRate   = payslip?.hourlyRate         ?? null;
  const taxCode      = payslip?.taxCode            ?? "1257L";

  // Bar widths — each deduction as % of gross, clamped so they never overflow
  const taxPct     = gross > 0 ? Math.min(Math.round((incomeTax / gross) * 100), 100) : 0;
  const niPct      = gross > 0 ? Math.min(Math.round((ni        / gross) * 100), 100) : 0;
  const pensionPct = gross > 0 ? Math.min(Math.round((pension   / gross) * 100), 100) : 0;
  // Net bar fills the remainder — no explicit calculation needed (flex-1)

  // Annual projections (monthly × 12)
  const annualGross = gross * 12;
  const annualNet   = net   * 12;

  // Tax-free hours (personal allowance £12,570 / 12 = £1,047.50/month)
  const monthlyAllowance = 1047.5;
  const taxFreeHours = hourlyRate && hourlyRate > 0
    ? Math.floor(monthlyAllowance / hourlyRate)
    : null;

  const wipeAndReset = () => {
    localStorage.clear();
    setPayslip(null);
    setShowHomeWarning(false);
  };

  return (
    <PrototypeScaffold step={hasData ? 1 : 0} nextHref="/upload" backHref="/manual-entry">
      {() => (
        <>
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
                  <div className="w-9 h-9 rounded-full bg-[#18231F] border border-[#263730] flex items-center justify-center text-[#FFAE34] shadow-inner">
                    <svg width="16" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                  </div>
                </div>

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
                  <button
                    type="button"
                    onClick={() => setSheetOpen(true)}
                    className="w-full py-3 bg-[#FFAE34] hover:bg-[#E59A2B] text-black text-xs font-bold rounded-xl transition-all border-0 shadow-sm uppercase tracking-wider cursor-pointer active:scale-[0.99]"
                  >
                    Scan payslip
                  </button>
                </div>

                <div className="grid grid-cols-3 gap-2.5 mb-6">
                  {["Take-Home", "Tax Paid", "Pension"].map((label) => (
                    <div key={label} className="w-full bg-[#34423d] border border-[#515a57] rounded-xl p-3 text-left">
                      <div className="text-white text-[9px] font-bold uppercase tracking-wider mb-1">{label}</div>
                      <div className="text-white font-bold text-sm tracking-widest">--</div>
                    </div>
                  ))}
                </div>
              </div>

            ) : (
              /* ── Dashboard ── */
              <div className="flex flex-col flex-1 overflow-y-auto custom-scrollbar pr-1">

                {/* Header */}
                <div className="flex justify-between items-center w-full my-4 shrink-0">
                  <Link href="/upload" className="text-[var(--sage)] text-base font-bold hover:text-[var(--ink)] transition-colors">‹</Link>
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
                    Net Pay · {payslip.month}
                  </span>
                  <div
                    className="text-[var(--ink)] text-3xl font-bold tracking-tight mb-1"
                    style={{ textShadow: "0 0 8px var(--border)" }}
                  >
                    {gbp(net)}
                  </div>
                  <div className="text-[var(--sage)] text-[11px]">
                    of <span className="text-[var(--ink)] font-bold">{gbp(gross)} gross</span>
                    {hourlyRate !== null && (
                      <> · <span className="text-[var(--ink)] font-bold">{gbp(hourlyRate)}/hr</span></>
                    )}
                  </div>
                </div>

                {/* Breakdown bar — widths from real data */}
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

                {/* Legend — every value sourced directly from payslip */}
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-[var(--sage)] mb-6">
                  <span className="flex items-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-[#FF9466]" />
                    Tax {gbp(incomeTax)}
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-[#5C7569]" />
                    NI {gbp(ni)}
                  </span>
                  {pension > 0 && (
                    <span className="flex items-center gap-1">
                      <span className="w-1 h-1 rounded-full bg-[#2A3E34]" />
                      Pension {gbp(pension)}
                    </span>
                  )}
                  <span className="flex items-center gap-1 text-[var(--ink)] font-bold">
                    <span className="w-1 h-1 rounded-full bg-[var(--ink)]" />
                    Net {gbp(net)}
                  </span>
                </div>

                {/* Tax bracket card */}
                <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl mb-3 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setBracketExpanded(!bracketExpanded)}
                    className="w-full p-4 flex items-center justify-between text-left focus:outline-none cursor-pointer border-0 bg-transparent"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-6 h-6 rounded-lg bg-[#2E201B] border border-[#4D2E24] text-[#FF9466] flex items-center justify-center font-bold text-xs">!</div>
                      <div>
                        <h3 className="text-[var(--ink)] text-xs font-bold leading-tight">Tax bracket info</h3>
                        <p className="text-[var(--sage)] text-[10px] mt-0.5">Tap to see what changes if you cross it</p>
                      </div>
                    </div>
                    <span className="text-[var(--sage)] text-xs">{bracketExpanded ? "▲" : "▼"}</span>
                  </button>
                  {bracketExpanded && (
                    <div className="px-4 pb-4 pt-1 border-t border-[var(--border)] text-[10px] text-[var(--sage)] leading-relaxed animate-fadeIn">
                      Your projected annual gross is{" "}
                      <span className="text-[var(--ink)] font-bold">{gbp(annualGross)}</span>.{" "}
                      {annualGross > 50270
                        ? <>You are already in the Higher Rate (40%) band — earnings above <span className="text-[var(--ink)] font-bold">£50,270</span> are taxed at 40%.</>
                        : <>Earnings above <span className="text-[var(--ink)] font-bold">£50,270</span> move into the Higher Rate (40%) band.{" "}
                            You are <span className="text-[var(--ink)] font-bold">{gbp(50270 - annualGross)}</span> away from that threshold.</>
                      }
                    </div>
                  )}
                </div>

                {/* Part-time card */}
                <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl mb-4 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setPartTimeExpanded(!partTimeExpanded)}
                    className="w-full p-4 flex items-center justify-between text-left focus:outline-none cursor-pointer border-0 bg-transparent"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-6 h-6 rounded-lg bg-[#1C2C24] border border-[#2B473A] text-[var(--ink)] flex items-center justify-center text-xs">🎓</div>
                      <div>
                        <h3 className="text-[var(--ink)] text-xs font-bold leading-tight">Working part-time at uni?</h3>
                        <p className="text-[var(--sage)] text-[10px] mt-0.5">Tap for your tax-free hours per month</p>
                      </div>
                    </div>
                    <span className="text-[var(--sage)] text-xs">{partTimeExpanded ? "▲" : "▼"}</span>
                  </button>
                  {partTimeExpanded && (
                    <div className="px-4 pb-4 pt-1 border-t border-[var(--border)] text-[10px] text-[var(--sage)] leading-relaxed animate-fadeIn">
                      Under a <span className="text-[var(--ink)] font-bold">{taxCode} tax code</span>, your personal
                      allowance is <span className="text-[var(--ink)] font-bold">£12,570/year</span> — about{" "}
                      <span className="text-[var(--ink)] font-bold">{gbp(monthlyAllowance)}/month</span> before tax applies.
                      {taxFreeHours !== null
                        ? <> At {gbp(hourlyRate!)}/hr that's roughly{" "}
                            <span className="text-[var(--ink)] font-bold">{taxFreeHours} hours/month</span> tax-free.</>
                        : <> Add your hourly rate when entering a payslip to see your tax-free hours.</>
                      }
                    </div>
                  )}
                </div>

                {/* Annual projection */}
                <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl p-4 mb-4 flex flex-col items-start shadow-xs">
                  <span className="text-[var(--sage)] text-[10px] uppercase font-mono tracking-wider mb-1">
                    Projected annual take-home
                  </span>
                  <div className="text-[var(--ink)] text-lg font-bold tracking-tight">{gbp(annualNet)}</div>
                  <div className="text-[var(--sage)] text-[10px] mt-0.5">
                    {gbp(net)}/month × 12 — based on {payslip.month}
                  </div>
                </div>

              </div>
            )}

            {/* ── Bottom nav ── */}
            <div className="basis-bottom-nav flex justify-center items-center gap-16 border-t border-[var(--border)] pt-4 mt-auto shrink-0 w-full relative z-20">
              <button
                type="button"
                onClick={() => { if (hasData) setShowHomeWarning(true); }}
                className="text-[var(--amber)] text-xs flex flex-col items-center gap-1 font-bold cursor-pointer border-0 bg-transparent focus:outline-none"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#FFAE34]" />
                Home
              </button>
              <button
                type="button"
                onClick={() => setPremiumFeature("insights")}
                className="text-[var(--sage)] text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-[var(--ink)] transition-colors border-0 bg-transparent focus:outline-none mt-2.5"
              >
                Insights
              </button>
            </div>

            {/* ── FAB ── */}
            <button
              type="button"
              onClick={() => setAskOpen(true)}
              className="absolute right-4 bottom-14 w-12 h-12 bg-[#FFAE34] hover:bg-[#E59A2B] text-black font-bold text-lg rounded-full flex items-center justify-center shadow-lg cursor-pointer border-0 active:scale-95 transition-transform z-50"
            >
              ?
            </button>

            {/* ── Sheet backdrop ── */}
            <button
              type="button"
              className={`fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity duration-300 z-40 ${sheetOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
              onClick={() => setSheetOpen(false)}
              aria-label="Close menu"
            />

            {/* ── Add payslip sheet ── */}
            <div className={`fixed bottom-0 left-0 right-0 max-w-sm mx-auto bg-[var(--surface)] border-t border-[var(--border)] rounded-t-2xl px-6 pt-3 pb-8 transition-transform duration-300 z-50 flex flex-col shadow-2xl ${sheetOpen ? "translate-y-0" : "translate-y-full"}`}>
              <div className="w-12 h-1.5 bg-[var(--surface-2)] rounded-full mx-auto mb-6" />
              <div className="text-[var(--ink)] text-base font-bold mb-4 uppercase tracking-wider">Add your payslip</div>
              <Link
                className="flex items-center gap-4 bg-[var(--surface-2)] border border-[var(--border)] text-[var(--ink)] p-4 rounded-xl mb-3 font-medium transition-all hover:opacity-90"
                href="/upload?source=file"
                onClick={() => setSheetOpen(false)}
              >
                📄 Upload PDF
              </Link>
              <Link
                className="flex items-center gap-4 bg-[var(--surface-2)] border border-[var(--border)] text-[var(--ink)] p-4 rounded-xl mb-6 font-medium transition-all hover:opacity-90"
                href="/upload"
                onClick={() => setSheetOpen(false)}
              >
                ✍️ Enter manually
              </Link>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                className="w-full py-3 bg-transparent border border-[var(--border)] text-[var(--sage)] hover:text-[var(--ink)] font-bold rounded-xl text-xs uppercase tracking-widest cursor-pointer transition-colors"
              >
                Cancel
              </button>
            </div>

            {/* ── Wipe warning modal ── */}
            {showHomeWarning && (
              <div className="absolute inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center p-5 z-50 animate-fadeIn">
                <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl p-5 flex flex-col text-left font-mono">
                  <div className="text-[var(--amber)] text-sm font-bold uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    ⚠️ Clear data?
                  </div>
                  <p className="text-[var(--ink)] text-xs leading-relaxed font-normal mb-6">
                    This will remove all saved payslips from this device. You'll need to scan or enter them again.
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

            {/* ── Premium modal ── */}
            {premiumFeature && (
              <div className="absolute inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center p-5 z-50 animate-fadeIn">
                <div className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl p-5 flex flex-col text-left font-mono">
                  <div className="text-[var(--amber)] text-sm font-bold uppercase tracking-wider mb-3">🔒 Premium Feature</div>
                  {premiumFeature === "insights" ? (
                    <>
                      <h3 className="text-white text-xs font-bold mb-3">Historical Pay Trend Analytics</h3>
                      <ul className="text-[var(--sage)] text-[11px] list-none p-0 m-0 flex flex-col gap-2 mb-6 font-normal">
                        <li>• Historic timeline graphing</li>
                        <li>• Tax year reconciliations</li>
                        <li>• Multi-job aggregate tracking</li>
                        <li>• Tax refund estimator</li>
                      </ul>
                    </>
                  ) : (
                    <>
                      <h3 className="text-white text-xs font-bold mb-3">Workspace Cloud Sync</h3>
                      <ul className="text-[var(--sage)] text-[11px] list-none p-0 m-0 flex flex-col gap-2 mb-6 font-normal">
                        <li>• Secure cloud backups</li>
                        <li>• Custom tax-code overrides</li>
                        <li>• Multiple profile workspaces</li>
                        <li>• Exportable HMRC ledger reports</li>
                      </ul>
                    </>
                  )}
                  <div className="flex flex-col gap-2">
                    <button
                      type="button"
                      onClick={() => alert("Sandbox: payment processing not active.")}
                      className="w-full py-2.5 bg-[var(--amber)] text-black font-bold rounded-xl text-[11px] uppercase tracking-wider border-0 cursor-pointer active:scale-95 transition-transform"
                    >
                      Upgrade for £2.99/mo
                    </button>
                    <button
                      type="button"
                      onClick={() => setPremiumFeature(null)}
                      className="w-full py-2.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--sage)] hover:text-[var(--ink)] font-semibold rounded-xl text-[11px] uppercase tracking-wider cursor-pointer transition-colors"
                    >
                      Back to dashboard
                    </button>
                  </div>
                </div>
              </div>
            )}

          </div>

          <AskSheet open={askOpen} onOpen={() => setAskOpen(true)} onClose={() => setAskOpen(false)} />
        </>
      )}
    </PrototypeScaffold>
  );
}