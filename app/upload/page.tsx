"use client";

import { useMemo, useState, useEffect, useRef, type SyntheticEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
import { parsePayslip } from "@/lib/Api";
import { createManualPayslip } from "@/lib/parse-pdf";
import type { Payslip } from "@/app/Types/Types";

const STORAGE_KEY = "slyp:payslips";

const EMPTY_MANUAL_FORM = {
  jobLabel: "Primary job",
  month: new Date().toISOString().slice(0, 7),
  grossPay: "",
  incomeTax: "",
  nationalInsurance: "",
  pensionContribution: "",
  netPay: "",
  taxCode: "",
  hourlyRate: "",
};

export default function UploadPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Core App Logic States (Preserved completely from your version)
  const [jobLabel, setJobLabel] = useState("Primary job");
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [manualMode, setManualMode] = useState(false);
  const [manualForm, setManualForm] = useState(EMPTY_MANUAL_FORM);

  // UI Flow Tracking States
  const [isCameraMode, setIsCameraMode] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState("");

  // Dynamically catch if user picked "Take a photo" vs "Upload PDF" from the home screen
  useEffect(() => {
    const source = searchParams.get("source");
    setIsCameraMode(source === "camera");
  }, [searchParams]);

  const canSubmitManual = useMemo(() => {
    return Boolean(
      manualForm.jobLabel.trim() &&
        manualForm.grossPay &&
        manualForm.netPay &&
        manualForm.incomeTax &&
        manualForm.nationalInsurance &&
        manualForm.taxCode.trim()
    );
  }, [manualForm]);

  const savePayslip = (payslip: Payslip) => {
    const raw = localStorage.getItem(STORAGE_KEY);
    const existing = raw ? (JSON.parse(raw) as Payslip[]) : [];
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...existing, payslip]));
    setMessage("Payslip added successfully.");
    setManualMode(false);
    setManualForm(EMPTY_MANUAL_FORM);
    router.push("/");
  };

  // Triggers when a file/photo is selected to match your workflow animation screenshot
  const handleNativeFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadedFileName(file.name);
    
    // Automatically submit the form to fire your real parsePayslip engine
    const syntheticEvent = {
      preventDefault: () => {},
      currentTarget: e.target.form
    } as unknown as SyntheticEvent<HTMLFormElement>;
    
    executeUpload(syntheticEvent, file);
  };

  const executeUpload = async (event: SyntheticEvent<HTMLFormElement>, directFile?: File) => {
    if (event) event.preventDefault();
    
    let file = directFile;
    if (!file && event) {
      const form = event.currentTarget;
      const fileInput = form.elements.namedItem("payslip") as HTMLInputElement;
      file = fileInput.files?.[0];
    }

    if (!file) {
      setMessage("Please select a file first.");
      return;
    }

    setIsUploading(true);
    setMessage(null);

    try {
      const parsed = await parsePayslip(file, jobLabel || "Primary job");
      if (!parsed.success || !parsed.payslip) {
        setManualForm({
          ...EMPTY_MANUAL_FORM,
          jobLabel: jobLabel || "Primary job",
          month: new Date().toISOString().slice(0, 7),
          grossPay: "",
          incomeTax: "",
          nationalInsurance: "",
          pensionContribution: "",
          netPay: "",
          taxCode: "",
          hourlyRate: "",
        });
        setManualMode(true);
        setMessage(`OCR reading failed. Missing fields: ${parsed.missingFields?.join(", ") || "unknown"}. Please complete details manually below.`);
        return;
      }
      savePayslip(parsed.payslip);
    } catch (error) {
      setManualMode(true);
      setMessage(error instanceof Error ? error.message : "Parsing extraction failed.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleManualSubmit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const payslip = createManualPayslip({
        ...manualForm,
        jobLabel: manualForm.jobLabel || "Primary job",
        month: manualForm.month || new Date().toISOString().slice(0, 7),
        pensionContribution: manualForm.pensionContribution || 0,
      });
      savePayslip(payslip);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Complete all fields.");
    }
  };
  return (
    <PrototypeScaffold
      step={1}
      nextHref="/"
      backHref="/"
      annotation={{
        number: "02 · Document Processor",
        title: manualMode ? "Manual Override Layout" : isCameraMode ? "Camera Hardware Core" : "On-Device PDF Engine",
        description: manualMode 
          ? "The extraction parser found an exception. Presenting fallback manual entry parameters to maintain pipeline stability."
          : "Fires localized token verification arrays directly against device storage partitions securely.",
      }}
    >
      {() => (
        <div className="basis-screen active relative h-full flex flex-col pt-4 overflow-y-auto custom-scrollbar">
          {/* Mobile Back Chevron Bar */}
          <div className="flex justify-between items-center mb-6 shrink-0">
            <Link href="/" className="text-gray-400 hover:text-white text-sm focus:outline-none">‹</Link>
            <h1 className="text-white text-sm font-medium tracking-tight">
              {manualMode ? "Manual Entry Fix" : "Add Payslip"}
            </h1>
            <div className="w-4 opacity-0">‹</div>
          </div>

          {/* MAIN CONDITIONAL VIEW SWITCH PANEL */}
          {!manualMode ? (
            /* VIEW STATE A: PROCESSING LOADER SCREEN OR INITIAL DROPZONE PICKER */
            <form onSubmit={(e) => e.preventDefault()} className="flex flex-col flex-1 justify-between">
              <div className="flex flex-col items-start w-full">
                
                {/* Real input fields linked to your state handlers hidden out of view */}
                <input 
                  id="payslip"
                  name="payslip"
                  type="file" 
                  ref={fileInputRef}
                  onChange={handleNativeFileChange}
                  accept={isCameraMode ? "image/*" : "application/pdf,image/*"}
                  capture={isCameraMode ? "environment" : undefined}
                  className="hidden"
                />

                {!isUploading && !uploadedFileName ? (
                  /* STEP 1: RENDER INITIAL ACTION CAPTURE WORKSPACE DROP BOX */
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full text-left border border-dashed border-[#232A26] bg-[#111513] hover:bg-[#161D1A] rounded-2xl p-8 transition-colors flex flex-col items-center justify-center gap-3 cursor-pointer py-16"
                  >
                    <span className="text-3xl">{isCameraMode ? "📷" : "📄"}</span>
                    <div className="text-white text-sm font-medium">
                      {isCameraMode ? "Snap your document paycheck" : "Choose a payslip PDF"}
                    </div>
                    <div className="text-gray-500 text-[11px] text-center px-4">
                      Tap anywhere inside this box window to mount local file selectors
                    </div>
                  </button>
                ) : (
                  /* STEP 2: RENDER RUNNING STATUS LOADING SCREENS MATCHING SCREENSHOT EXACTLY */
                  <div className="flex flex-col items-start w-full animate-fadeIn">
                    <h1 className="text-white text-xl font-medium tracking-tight mb-1">
                      Reading your payslip
                    </h1>
                    <div className="text-xs font-mono text-[#FFAE34] mb-4 truncate w-full max-w-xs">
                      File: {uploadedFileName || "Processing..."}
                    </div>

                    <div className="text-gray-300 text-sm leading-relaxed mb-4 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                      <span className={isUploading ? "animate-pulse text-[#FFAE34]" : ""}>✓ Hourly rate</span>
                      <span className={isUploading ? "animate-pulse text-[#FFAE34]" : ""}>✓ Gross pay</span>
                      <span>✓ Income tax</span>
                      <span>✓ National Ins.</span>
                      <span>✓ Net pay</span>
                    </div>

                    <p className="text-gray-500 text-xs leading-relaxed font-normal">
                      Extracting line items on-device. The original file is discarded the instant this finishes.
                    </p>
                  </div>
                )}

                {message && (
                  <div className="text-amber-400 bg-amber-950/20 border border-amber-900/40 rounded-xl p-3 text-[10px] font-mono mt-4 leading-relaxed">
                    {message}
                  </div>
                )}
              </div>

              {/* Loader controls footer links */}
              <div className="mt-auto pb-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setManualMode(true)}
                  className="w-full text-center text-gray-500 hover:text-white font-medium text-xs py-2 transition-colors cursor-pointer"
                >
                  Skip to manual input layout
                </button>
              </div>
            </form>
          ) : (
            /* VIEW STATE B: RENDER YOUR EXACT MANUAL FORM BUT STYLED WITHIN THE SMARTPHONE CONTAINER */
            <form onSubmit={handleManualSubmit} className="flex flex-col gap-3.5 flex-1 pb-2">
              
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Job label description</label>
                <input 
                  type="text"
                  value={manualForm.jobLabel}
                  onChange={(e) => setManualForm(curr => ({ ...curr, jobLabel: e.target.value }))}
                  className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Period Month</label>
                  <input 
                    type="month"
                    value={manualForm.month}
                    onChange={(e) => setManualForm(curr => ({ ...curr, month: e.target.value }))}
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2 px-3 text-xs focus:outline-none focus:border-[#FFAE34] invert-calendar"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Tax Code</label>
                  <input 
                    type="text"
                    value={manualForm.taxCode}
                    placeholder="e.g. 1257L"
                    onChange={(e) => setManualForm(curr => ({ ...curr, taxCode: e.target.value }))}
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34] font-mono uppercase"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Gross pay total</label>
                  <input 
                    type="number"
                    step="0.01"
                    value={manualForm.grossPay}
                    onChange={(e) => setManualForm(curr => ({ ...curr, grossPay: e.target.value }))}
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34]"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Net Take-Home</label>
                  <input 
                    type="number"
                    step="0.01"
                    value={manualForm.netPay}
                    onChange={(e) => setManualForm(curr => ({ ...curr, netPay: e.target.value }))}
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Income tax cut</label>
                  <input 
                    type="number"
                    step="0.01"
                    value={manualForm.incomeTax}
                    onChange={(e) => setManualForm(curr => ({ ...curr, incomeTax: e.target.value }))}
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34]"
                  />
                </div>
                                <div className="flex flex-col gap-1.5">
                  <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">National Ins. (NI)</label>
                  <input 
                    type="number"
                    step="0.01"
                    value={manualForm.nationalInsurance}
                    onChange={(e) => setManualForm(curr => ({ ...curr, nationalInsurance: e.target.value }))}
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34]"
                  />
                </div>
              </div>

              {/* FIXED: Emoji and text wrapper safely contained in valid HTML tags */}
              {message && (
                <div className="text-amber-400 bg-amber-950/20 border border-amber-900/40 rounded-xl p-3 text-[10px] font-mono leading-relaxed mt-2">
                  <span>⚠️</span> Alert: {message}
                </div>
              )}

              {/* Submission Button Blocks */}
              <div className="mt-auto pt-4 shrink-0">
                <button
                  type="submit"
                  disabled={!canSubmitManual}
                  className="w-full py-3 bg-[#FFAE34] hover:bg-[#E59A2B] disabled:bg-gray-800 disabled:text-gray-500 text-black font-semibold rounded-xl text-xs transition-colors cursor-pointer focus:outline-none"
                >
                  Save Manual Overrides
                </button>
                <button
                  type="button"
                  onClick={() => { setManualMode(false); setMessage(null); setUploadedFileName(""); }}
                  className="block w-full py-2.5 bg-transparent text-gray-500 hover:text-white text-xs text-center font-medium mt-1 focus:outline-none cursor-pointer"
                >
                  ← Go Back To File Picker
                </button>
              </div>
            </form>
          )}

        </div>
      )}
    </PrototypeScaffold>
  );
}
