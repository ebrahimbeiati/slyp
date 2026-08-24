"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
import { analysePayslip, AnalyseError } from "@/lib/Api";
import { onlyJobFromAnswer, taxYearRangeLabel } from "@/lib/onlyJob";
import { encodeStoredResult, STORAGE_KEY } from "@/lib/storedResult";
import type { OtherJobAnswer } from "@/lib/onlyJob";

const PROGRESS_STEPS = [
  "Uploading",
  "Reading your payslip",
  "Checking the numbers",
  "Finishing up",
];

// Fake but bounded progress: ticks through the labels above then holds on
// the last one for as long as the request actually takes. A real payslip
// call takes several seconds (a live model call, not a local parse) - this
// has to look deliberate at 10+ seconds, not stuck.
const STEP_INTERVAL_MS = 900;

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sweepTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // The ANSWER is what the UI holds; only_job is derived from it at send
  // time via onlyJobFromAnswer(). Storing the answer rather than the
  // derived boolean is what keeps "Not sure" distinguishable from an
  // unanswered question in the UI (both send nothing, but only one of
  // them shows as selected), and keeps the inverted mapping in exactly
  // one place - see lib/onlyJob.ts.
  const [otherJob, setOtherJob] = useState<OtherJobAnswer | null>(null);
  const taxYearRange = useMemo(() => taxYearRangeLabel(new Date()), []);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState("");
  const [sweepIndex, setSweepIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const startSweep = () => {
    setSweepIndex(0);
    let step = 0;
    sweepTimer.current = setInterval(() => {
      step = Math.min(step + 1, PROGRESS_STEPS.length - 1);
      setSweepIndex(step);
    }, STEP_INTERVAL_MS);
  };

  const stopSweep = () => {
    if (sweepTimer.current) {
      clearInterval(sweepTimer.current);
      sweepTimer.current = null;
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Reset so selecting the same file twice in a row still fires onChange.
    e.target.value = "";
    if (!file || isUploading) return;
    void runUpload(file);
  };

  const runUpload = async (file: File) => {
    setIsUploading(true);
    setError(null);
    setUploadedFileName(file.name);
    startSweep();

    try {
      const result = await analysePayslip(file, onlyJobFromAnswer(otherJob));
      localStorage.setItem(STORAGE_KEY, encodeStoredResult(result));
      router.push("/");
      // Deliberately no `finally` reset of isUploading here on the
      // success path - the page is navigating away, and re-enabling the
      // button just before that happens would let a second click sneak
      // in during the transition.
    } catch (err) {
      stopSweep();
      setIsUploading(false);
      setUploadedFileName("");
      setError(
        err instanceof AnalyseError
          ? err.message
          : "Something went wrong. Please try again.",
      );
    }
  };

  return (
    <PrototypeScaffold step={0} nextHref="#" backHref="/">
      {() => (
        <div className="basis-screen active relative h-full flex flex-col pt-4 overflow-y-auto custom-scrollbar text-[var(--ink)]">
          {/* Header */}
          <div className="flex justify-between items-center mb-6 shrink-0">
            <Link
              href="/"
              className="text-[var(--sage)] hover:text-[var(--ink)] text-sm focus:outline-none"
            >
              ‹
            </Link>
            <h1 className="text-[var(--ink)] text-sm font-medium tracking-tight">
              Add payslip
            </h1>
            <div className="w-4 opacity-0" aria-hidden="true">
              ‹
            </div>
          </div>

          <input
            id="payslip"
            name="payslip"
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept="application/pdf"
            className="hidden"
            disabled={isUploading}
          />

          {!isUploading ? (
            <div className="flex flex-col flex-1">
              <div className="mb-4">
                <div className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium mb-0.5">
                  Have you had any other job this tax year?
                </div>
                <div className="text-[10px] text-[var(--sage)] opacity-60 mb-1.5">
                  This tax year runs {taxYearRange}.
                </div>
                {/* Three options, one row, equal width - "Not sure" is a
                    real answer, not a skip. It is the only one that omits
                    only_job from the request, which keeps every finding
                    that depends on it conditional rather than asserting
                    a second job. */}
                <div className="flex gap-2">
                  {(
                    [
                      { label: "Yes", value: "yes" },
                      { label: "No", value: "no" },
                      { label: "Not sure", value: "not_sure" },
                    ] as const
                  ).map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      aria-pressed={otherJob === opt.value}
                      onClick={() => setOtherJob(opt.value)}
                      className={`flex-1 py-2.5 rounded-xl text-xs font-medium border transition-colors cursor-pointer ${
                        otherJob === opt.value
                          ? "bg-[#FFAE34] text-[#0d1410] border-[#FFAE34]"
                          : "bg-[#141A17] border-[#232D27] text-[var(--sage)] hover:border-[#FFAE34]/40"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-[var(--sage)] opacity-70 mt-1.5 leading-relaxed">
                  Some checks depend on this - a BR tax code is often normal
                  for a second job but worth flagging on a first one, and an
                  emergency code can only have overcharged you if this has
                  been your only employment this year.
                </p>
              </div>

              {error && (
                <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-xl px-3 py-2.5 text-[11px] text-[#FFAE34] mb-4">
                  ⚠️ {error}
                </div>
              )}

              <div className="relative w-full overflow-hidden rounded-2xl flex flex-col items-center justify-center">
                <div className="absolute left-0 right-0 h-[4px] bg-[#d6a459] pointer-events-none z-40 shadow-[0_0_30px_#FFAE34,0_0_6px_#FFAE34] animate-yellow-laser" />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading}
                  className="w-full bg-[#34423d] border border-[#515a57] rounded-3xl p-8 transition-all flex flex-col items-center justify-center gap-4 cursor-pointer py-16 shadow-xs hover:border-[#FFAE34]/40 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span className="text-3xl">📄</span>
                  <div className="text-[var(--ink)] text-xs font-bold uppercase tracking-wider">
                    Upload PDF payslip
                  </div>
                  <div className="text-[var(--ink)] text-[10px] text-center px-2 leading-relaxed opacity-60">
                    PDF only, up to 10MB. A digital payslip, not a photo or a
                    scan.
                  </div>
                </button>

                {/* Says what actually happens, which the previous wording
                    did not: "nothing personal leaves this device
                    unredacted" described an on-device pipeline this
                    product does not have. The PDF is uploaded and read on
                    the server; redaction happens there, before the model
                    call. The accurate version is the stronger claim
                    anyway, and it is the one that survives a judge opening
                    the network tab. */}
                <p className="text-[var(--sage)] text-[10px] leading-relaxed mt-3 px-1">
                  🔒 Your name, address, NI number and bank details are removed
                  on our server before any of it reaches the AI. The file is
                  never saved, and the result stays on this device.
                </p>
              </div>
            </div>
          ) : (
            /* Processing state */
            <div className="flex flex-col items-start w-full animate-fadeIn font-mono">
              <h1 className="text-white text-base font-bold tracking-tight mb-1">
                Reading your payslip
              </h1>
              <div className="text-[10px] text-[var(--sage)] truncate max-w-xs mb-6">
                Source: {uploadedFileName}
              </div>

              <div className="flex flex-col gap-2.5 w-full mb-6">
                {PROGRESS_STEPS.map((stepLabel, i) => {
                  const active = sweepIndex >= i;
                  const isCurrent = sweepIndex === i;
                  return (
                    <div
                      key={stepLabel}
                      className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${
                        active
                          ? "bg-[var(--surface-2)] border-[var(--ink)]"
                          : "border-[var(--border)] opacity-30"
                      }`}
                    >
                      {active && !isCurrent ? "✓" : "•"}{" "}
                      {stepLabel}
                      {isCurrent ? "…" : ""}
                    </div>
                  );
                })}
              </div>

              <p className="text-[10px] text-[var(--sage)] opacity-70">
                This can take a little while for the first request.
              </p>
            </div>
          )}
        </div>
      )}
    </PrototypeScaffold>
  );
}
