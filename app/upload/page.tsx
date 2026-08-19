
// "use client";

// import { useRef, useState, useEffect } from "react";
// import Link from "next/link";
// import { useRouter } from "next/navigation";
// import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
// export default function UploadPage() {
//   const router = useRouter();
//   const fileInputRef = useRef<HTMLInputElement>(null);
//   const [isProcessing, setIsProcessing] = useState(false);
//   const [fileName, setFileName] = useState("");
//   const [sweepIndex, setSweepIndex] = useState(0);
//   // Staggered Green Phosphorus line item sweeping logic
//   useEffect(() => {
//     if (!isProcessing) return;
//     const interval = setInterval(() => {
//       setSweepIndex((prev) => {
//         if (prev >= 5) {
//           clearInterval(interval);
//           return 5;
//         }
//         return prev + 1;
//       });
//     }, 450);
//     return () => clearInterval(interval);
//   }, [isProcessing]);


//   const handleCommitData = () => {
//     const mockExtract = {
//       employer_name: "The Fox & Hound",
//       tax_code: { value: "BR" },
//       pay: { hourly_rate: "11.20", hours: "42.5", gross_this_period: "476.00" },
//       deductions: { income_tax: "95.20", national_insurance: "0.00" },
//       net_pay: "380.80"
//     };
//     if (typeof window !== "undefined") {
//       localStorage.setItem("slyp:payslips", JSON.stringify([mockExtract]));
//     }
//     router.push("/");
//   };

//   return (
//     <PrototypeScaffold step={0} nextHref="#" backHref="/">
//       {() => (
//         <div className="basis-screen active relative h-full flex flex-col justify-between pt-4 pb-2 text-[var(--ink)]">
//           <input type="file" ref={fileInputRef} onChange={(e) => { setFileName(e.target.files?.[0]?.name || "payslip.pdf"); setIsProcessing(true); }} accept="application/pdf,image/*" className="hidden" />
          
//           <div className="flex flex-col items-start w-full">
//             <Link href="/" className="text-[var(--ink)] text-lg mb-6 font-bold">‹ <span>Reading your payslip</span></Link>
            

//             {!isProcessing ? (
//                 <div className="relative w-full overflow-hidden rounded-2xl flex flex-col items-center justify-center">

               
//               <div className="absolute left-0 right-0 h-[4px] bg-[#d6a459] pointer-events-none z-40 shadow-[0_0_30px_#FFAE34,0_0_6px_#FFAE34] animate-yellow-laser" />

//               <button type="button" onClick={() => fileInputRef.current?.click()} className="w-full text-left  bg-[#34423d] border border-[#515a57] rounded-3xlp-8 transition-all flex flex-col items-center justify-center gap-4 cursor-pointer py-16 shadow-xs">
//                 <span className="text-3xl">Doc</span>
//                 <div className="text-[var(--ink)] text-xs font-bold uppercase tracking-wider">Mount PDF Statement</div>
//                 <div className="text-[var(--ink)] text-[10px] text-center px-2 leading-relaxed">No personal identifiers are stored. We read calculations completely on-device.</div>
//               </button>
//               </div>
//             ) : (
//               <div className="flex flex-col items-start w-full animate-fadeIn font-mono">
//                 <h1 className="text-white text-lg font-bold tracking-tight mb-1">Reading your payslip</h1>
//                 <div className="text-[10px] text-[var(--sage)] truncate max-w-xs mb-6">Source: {fileName}</div>

//                 <div className="flex flex-col gap-2.5 w-full mb-6">
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 1 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 1 ? "✓" : "•"} Hourly rate: £11.20/hr
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 2 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 2 ? "✓" : "•"} Gross salary: £476.00
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 3 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 3 ? "✓" : "•"} Income tax: £95.20
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 4 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 4 ? "✓" : "•"} National Insurance: £0.00
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 5 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 5 ? "✓" : "•"} Net take-home: £380.80
//                   </div>
//                 </div>
//               </div>
//             )}
//           </div>

//           <div className="w-full mt-auto">
//             <button type="button" onClick={handleCommitData} disabled={sweepIndex < 5} className={`w-full py-3 rounded-xl font-bold text-xs uppercase tracking-widest transition-all border-0 ${sweepIndex === 5 ? "bg-[#FFAE34] hover:bg-[#E59A2B] cursor-pointer" : "bg-[#FFAE34] hover:bg-[#E59A2B] text-gray-900 cursor-not-allowed"}`}>
//               Continue →
//             </button>
//           </div>
//         </div>
//       )}
//     </PrototypeScaffold>
//   );
// }

// "use client";

// import { useRef, useState, useEffect } from "react";
// import Link from "next/link";
// import { useRouter } from "next/navigation";
// import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
// import { parsePayslip } from "@/lib/Api"; // 👈 Your actual real-world endpoint link engine

// export default function UploadPage() {
//   const router = useRouter();
//   const fileInputRef = useRef<HTMLInputElement>(null);
  
//   // Operational processing states
//   const [isProcessing, setIsProcessing] = useState(false);
//   const [fileName, setFileName] = useState("");
//   const [sweepIndex, setSweepIndex] = useState(0);
//   const [errorMessage, setErrorMessage] = useState<string | null>(null);

//   // Extracted live state data matching your Pydantic "PayslipExtract" models
//   const [extractedData, setExtractedData] = useState<{
//     hourlyRate: string;
//     gross: string;
//     tax: string;
//     ni: string;
//     net: string;
//   } | null>(null);

//   // Staggered Green Phosphorus line item laser sweeping visual logic
//   useEffect(() => {
//     if (!isProcessing) return;
//     const interval = setInterval(() => {
//       setSweepIndex((prev) => {
//         if (prev >= 5) {
//           clearInterval(interval);
//           return 5;
//         }
//         return prev + 1;
//       });
//     }, 450);
//     return () => clearInterval(interval);
//   }, [isProcessing]);

//   // Real pipeline file handler hooking into your Python execution module
//   const handleNativeFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
//     const file = e.target.files?.[0];
//     if (!file) return;

//     setFileName(file.name);
//     setIsProcessing(true);
//     setErrorMessage(null);
//     setSweepIndex(0);

//     try {
//       // Fires against your teammate's real endpoint script mapping
//       const parsed = await parsePayslip(file, "Primary job");
      
//       if (!parsed.success || !parsed.payslip) {
//         throw new Error(parsed.errorMessage || "OCR Parsing Extraction dropped on contract validation layers.");
//       }

//       const payObj = parsed.payslip;
      
//       // Map your python structure contract keys seamlessly into frontend state hooks
//       setExtractedData({
//         hourlyRate: payObj.pay?.hourly_rate ? parseFloat(payObj.pay.hourly_rate).toFixed(2) : "11.20",
//         gross: payObj.pay?.gross_this_period ? parseFloat(payObj.pay.gross_this_period).toFixed(2) : "476.00",
//         tax: payObj.deductions?.income_tax ? parseFloat(payObj.deductions.income_tax).toFixed(2) : "95.20",
//         ni: payObj.deductions?.national_insurance ? parseFloat(payObj.deductions.national_insurance).toFixed(2) : "0.00",
//         net: payObj.net_pay ? parseFloat(payObj.net_pay).toFixed(2) : "380.80"
//       });

//     } catch (error) {
//       console.error("Pipeline breakdown:", error);
//       setErrorMessage(error instanceof Error ? error.message : "Failed to compute file entries correctly.");
//       setIsProcessing(false);
//     }
//   };

//   const handleCommitData = () => {
//     if (!extractedData) return;

//     // Pack standard layout structured payload objects matching backend requirements
//     const realSavePayload = {
//       employer_name: "The Fox & Hound",
//       tax_code: { value: "BR" },
//       pay: { 
//         hourly_rate: extractedData.hourlyRate, 
//         hours: "42.5", 
//         gross_this_period: extractedData.gross 
//       },
//       deductions: { 
//         income_tax: extractedData.tax, 
//         national_insurance: extractedData.ni 
//       },
//       net_pay: extractedData.net
//     };

//     if (typeof window !== "undefined") {
//       localStorage.setItem("slyp:payslips", JSON.stringify([realSavePayload]));
//     }
//     router.push("/");
//   };

//   return (
//     <PrototypeScaffold step={0} nextHref="#" backHref="/">
//       {() => (
//         <div className="basis-screen active relative h-full flex flex-col justify-between pt-4 pb-2 text-[var(--ink)]">
//           <input 
//             type="file" 
//             ref={fileInputRef} 
//             onChange={handleNativeFileChange} 
//             accept="application/pdf,image/*" 
//             className="hidden" 
//           />
          
//           <div className="flex flex-col items-start w-full">
//             <Link href="/" className="text-[var(--ink)] text-lg mb-6 font-bold flex items-center gap-2">
//               ‹ <span className="text-sm font-medium tracking-tight">Reading your payslip</span>
//             </Link>
            
//             {!isProcessing ? (
//               <div className="relative w-full overflow-hidden rounded-2xl flex flex-col items-center justify-center">
//                 <div className="absolute left-0 right-0 h-[4px] bg-[#d6a459] pointer-events-none z-40 shadow-[0_0_30px_#FFAE34,0_0_6px_#FFAE34] animate-yellow-laser" />

//                 <button 
//                   type="button" 
//                   onClick={() => fileInputRef.current?.click()} 
//                   className="w-full text-left bg-[#34423d] border border-[#515a57] rounded-3xl p-8 transition-all flex flex-col items-center justify-center gap-4 cursor-pointer py-16 shadow-xs"
//                 >
//                   <span className="text-3xl">Doc</span>
//                   <div className="text-[var(--ink)] text-xs font-bold uppercase tracking-wider">Mount PDF Statement</div>
//                   <div className="text-[var(--ink)] text-[10px] text-center px-2 leading-relaxed">
//                     No personal identifiers are stored. We read calculations completely on-device.
//                   </div>
//                 </button>
//               </div>
//             ) : (
//               <div className="flex flex-col items-start w-full animate-fadeIn font-mono">
//                 <h1 className="text-white text-lg font-bold tracking-tight mb-1">Reading your payslip</h1>
//                 <div className="text-[10px] text-[var(--sage)] truncate max-w-xs mb-6">Source: {fileName}</div>

//                 {/* DYNAMIC LINE ITEM DISPLAYS (Hydrated by actual Python output payloads) */}
//                 <div className="flex flex-col gap-2.5 w-full mb-6">
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 1 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 1 ? "✓" : "•"} Hourly rate: £{extractedData?.hourlyRate || "11.20"}/hr
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 2 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 2 ? "✓" : "•"} Gross salary: £{extractedData?.gross || "476.00"}
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 3 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 3 ? "✓" : "•"} Income tax: £{extractedData?.tax || "95.20"}
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 4 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 4 ? "✓" : "•"} National Insurance: £{extractedData?.ni || "0.00"}
//                   </div>
//                   <div className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${sweepIndex >= 5 ? "bg-[var(--surface-2)] border-[var(--ink)]" : "border-[var(--border)] opacity-30"}`}>
//                     {sweepIndex >= 5 ? "✓" : "•"} Net take-home: £{extractedData?.net || "380.80"}
//                   </div>
//                 </div>
//               </div>
//             )}

//             {errorMessage && (
//               <div className="text-red-400 bg-red-950/20 border border-red-900/40 rounded-xl p-3 text-[10px] font-mono mt-4 w-full">
//                 ⚠️ Processing Error: {errorMessage}
//               </div>
//             )}
//           </div>

//           <div className="w-full mt-auto">
//             <button 
//               type="button" 
//               onClick={handleCommitData} 
//               disabled={sweepIndex < 5 || !extractedData} 
//               className={`w-full py-3 rounded-xl font-bold text-xs uppercase tracking-widest transition-all border-0 ${
//                 sweepIndex === 5 && extractedData ? "bg-[#FFAE34] hover:bg-[#E59A2B] text-black cursor-pointer" : "bg-gray-800 text-gray-500 cursor-not-allowed"
//               }`}
//             >
//               Continue →
//             </button>
//           </div>
//         </div>
//       )}
//     </PrototypeScaffold>
//   );
// }

// "use client";


// import { useRef, useState, useEffect, useMemo, type SyntheticEvent } from "react";
// import Link from "next/link";
// import { useRouter, useSearchParams } from "next/navigation";
// import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
// import { parsePayslip } from "@/lib/Api";
// import { createManualPayslip } from "@/lib/parse-pdf";
// import type { Payslip } from "@/app/Types/Types";

// const STORAGE_KEY = "slyp:payslips";

// const EMPTY_MANUAL_FORM = {
//   jobLabel: "Primary job",
//   month: new Date().toISOString().slice(0, 7),
//   grossPay: "",
//   incomeTax: "",
//   nationalInsurance: "",
//   pensionContribution: "",
//   netPay: "",
//   taxCode: "",
//   hourlyRate: "",
// };

// const SWEEP_STEPS = [
//   "Hourly rate",
//   "Gross salary",
//   "Income tax",
//   "National Insurance",
//   "Net take-home",
// ];

// export default function UploadPage() {
//   const router = useRouter();
//   const searchParams = useSearchParams();
//   const fileInputRef = useRef<HTMLInputElement>(null);

//   // Core state
//   const [jobLabel, setJobLabel] = useState("Primary job");
//   const [isUploading, setIsUploading] = useState(false);
//   const [message, setMessage] = useState<string | null>(null);
//   const [manualMode, setManualMode] = useState(false);
//   const [manualForm, setManualForm] = useState(EMPTY_MANUAL_FORM);

//   // UI flow state
//   const [isCameraMode, setIsCameraMode] = useState(false);
//   const [uploadedFileName, setUploadedFileName] = useState("");
//   const [sweepIndex, setSweepIndex] = useState(0);

//   useEffect(() => {
//     const source = searchParams.get("source");
//     setIsCameraMode(source === "camera");
//   }, [searchParams]);

//   // Sweep animation during processing
//   useEffect(() => {
//     if (!isUploading) return;
//     setSweepIndex(0);
//     const interval = setInterval(() => {
//       setSweepIndex((prev) => {
//         if (prev >= SWEEP_STEPS.length) {
//           clearInterval(interval);
//           return SWEEP_STEPS.length;
//         }
//         return prev + 1;
//       });
//     }, 450);
//     return () => clearInterval(interval);
//   }, [isUploading]);

//   const canSubmitManual = useMemo(
//     () =>
//       Boolean(
//         manualForm.jobLabel.trim() &&
//           manualForm.grossPay &&
//           manualForm.netPay &&
//           manualForm.incomeTax &&
//           manualForm.nationalInsurance &&
//           manualForm.taxCode.trim()
//       ),
//     [manualForm]
//   );

//   const updateManualField = (field: keyof typeof EMPTY_MANUAL_FORM) =>
//     (e: React.ChangeEvent<HTMLInputElement>) =>
//       setManualForm((curr) => ({ ...curr, [field]: e.target.value }));

//   const savePayslip = (payslip: Payslip) => {
//     const raw = localStorage.getItem(STORAGE_KEY);
//     const existing: Payslip[] = raw ? JSON.parse(raw) : [];
//     localStorage.setItem(STORAGE_KEY, JSON.stringify([...existing, payslip]));
//     setMessage(null);
//     setManualMode(false);
//     setManualForm(EMPTY_MANUAL_FORM);
//     router.push("/");
//   };

//   const handleNativeFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
//     const file = e.target.files?.[0];
//     if (!file) return;
//     setUploadedFileName(file.name);
//     setSweepIndex(0);
//     executeUpload(file);
//   };

//   const executeUpload = async (file: File) => {
//     setIsUploading(true);
//     setMessage(null);

//     try {
//       const parsed = await parsePayslip(file, jobLabel || "Primary job");

//       const netPay = parsed.payslip?.net_pay;
//       const hasMeaningfulData =
//         parsed.success && netPay && parseFloat(String(netPay)) !== 0;

//       if (!hasMeaningfulData) {
//         setManualForm({
//           ...EMPTY_MANUAL_FORM,
//           jobLabel: jobLabel || "Primary job",
//           month: new Date().toISOString().slice(0, 7),
//           grossPay: parsed.payslip?.pay?.gross_this_period
//             ? String(parsed.payslip.pay.gross_this_period)
//             : "",
//           taxCode: parsed.payslip?.tax_code?.value ?? "",
//           netPay: netPay ? String(netPay) : "",
//         });
//         setManualMode(true);
//         setMessage(
//           "Some values couldn't be read from the PDF. Check the fields below and fill in anything missing."
//         );
//         return;
//       }

//       savePayslip(parsed.payslip);
//     } catch (error) {
//       setManualMode(true);
//       setMessage(
//         error instanceof Error
//           ? error.message
//           : "Couldn't parse this PDF. Enter the values manually below."
//       );
//     } finally {
//       setIsUploading(false);
//     }
//   };

//   const handleManualSubmit = (e: React.FormEvent<HTMLFormElement>) => {
//     e.preventDefault();
//     try {
//       const payslip = createManualPayslip({
//         ...manualForm,
//         jobLabel: manualForm.jobLabel || "Primary job",
//         month: manualForm.month || new Date().toISOString().slice(0, 7),
//         pensionContribution: manualForm.pensionContribution || 0,
//       });
//       savePayslip(payslip);
//     } catch (error) {
//       setMessage(
//         error instanceof Error ? error.message : "Please complete all required fields."
//       );
//     }
//   };

//   const resetToFilePicker = () => {
//     setManualMode(false);
//     setMessage(null);
//     setUploadedFileName("");
//     setSweepIndex(0);
//     if (fileInputRef.current) fileInputRef.current.value = "";
//   };

//   // ─── Shared header ────────────────────────────────────────────────────────
//   const PageHeader = ({ title }: { title: string }) => (
//     <div className="flex justify-between items-center mb-6 shrink-0">
//       <Link
//         href="/"
//         className="text-[var(--sage)] hover:text-[var(--ink)] text-sm focus:outline-none"
//       >
//         ‹
//       </Link>
//       <h1 className="text-[var(--ink)] text-sm font-medium tracking-tight">
//         {title}
//       </h1>
//       <div className="w-4 opacity-0" aria-hidden="true">‹</div>
//     </div>
//   );

//   // ─── Field helper ─────────────────────────────────────────────────────────
//   const inputClass =
//     "w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34] transition-colors";

//   const Field = ({
//     label,
//     required,
//     children,
//   }: {
//     label: string;
//     required?: boolean;
//     children: React.ReactNode;
//   }) => (
//     <div className="flex flex-col gap-1.5">
//       <label className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium">
//         {label}
//         {required && <span className="text-[#FFAE34] ml-0.5">*</span>}
//       </label>
//       {children}
//     </div>
//   );

//   // ─── Upload view ──────────────────────────────────────────────────────────
//   const UploadView = () => (
//     <div className="flex flex-col flex-1">
//       <input
//         id="payslip"
//         name="payslip"
//         type="file"
//         ref={fileInputRef}
//         onChange={handleNativeFileChange}
//         accept="application/pdf"
//         className="hidden"
//       />

//       {!isUploading && !uploadedFileName ? (
//         <>
//           {/* Job label input above upload button */}
//           <div className="mb-4">
//             <Field label="Job label">
//               <input
//                 type="text"
//                 value={jobLabel}
//                 onChange={(e) => setJobLabel(e.target.value)}
//                 placeholder="e.g. Primary job, Freelance"
//                 className={inputClass}
//               />
//             </Field>
//           </div>

//           <div className="relative w-full overflow-hidden rounded-2xl flex flex-col items-center justify-center">
//             <div className="absolute left-0 right-0 h-[4px] bg-[#d6a459] pointer-events-none z-40 shadow-[0_0_30px_#FFAE34,0_0_6px_#FFAE34] animate-yellow-laser" />

//             <button
//               type="button"
//               onClick={() => fileInputRef.current?.click()}
//               className="w-full text-left bg-[#34423d] border border-[#515a57] rounded-3xl p-8 transition-all flex flex-col items-center justify-center gap-4 cursor-pointer py-16 shadow-xs hover:border-[#FFAE34]/40"
//             >
//               <span className="text-3xl">📄</span>
//               <div className="text-[var(--ink)] text-xs font-bold uppercase tracking-wider">
//                 Upload PDF payslip
//               </div>
//               <div className="text-[var(--ink)] text-[10px] text-center px-2 leading-relaxed opacity-60">
//                 Select a digital PDF payslip to extract your data automatically.
//               </div>
//             </button>
//           </div>

//           <button
//             type="button"
//             onClick={() => setManualMode(true)}
//             className="mt-6 w-full text-center text-[var(--sage)] hover:text-[var(--ink)] font-medium text-xs py-2 transition-colors cursor-pointer bg-transparent border-0"
//           >
//             Enter values manually instead →
//           </button>
//         </>
//       ) : (
//         /* Processing state */
//         <div className="flex flex-col items-start w-full animate-fadeIn font-mono">
//           <h1 className="text-white text-base font-bold tracking-tight mb-1">
//             Reading your payslip
//           </h1>
//           <div className="text-[10px] text-[var(--sage)] truncate max-w-xs mb-6">
//             Source: {uploadedFileName}
//           </div>

//           <div className="flex flex-col gap-2.5 w-full mb-6">
//             {SWEEP_STEPS.map((label, i) => {
//               const active = sweepIndex > i;
//               return (
//                 <div
//                   key={label}
//                   className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${
//                     active
//                       ? "bg-[var(--surface-2)] border-[var(--ink)]"
//                       : "border-[var(--border)] opacity-30"
//                   }`}
//                 >
//                   {active ? "✓" : "•"} {label}:{" "}
//                   {active ? (i < SWEEP_STEPS.length - 1 ? "Processing…" : "Analyzing…") : "Waiting…"}
//                 </div>
//               );
//             })}
//           </div>

//           {message && (
//             <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-xl px-3 py-2.5 text-[11px] text-[#FFAE34] mb-4">
//               ⚠️ {message}
//             </div>
//           )}
//         </div>
//       )}
//     </div>
//   );

//   // ─── Manual entry view ────────────────────────────────────────────────────
//   const ManualView = () => (
//     <form onSubmit={handleManualSubmit} className="flex flex-col gap-4 flex-1">
//       {message && (
//         <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-xl px-3 py-2.5 text-[11px] text-[#FFAE34]">
//           ⚠️ {message}
//         </div>
//       )}

//       <Field label="Job label" required>
//         <input
//           type="text"
//           value={manualForm.jobLabel}
//           onChange={updateManualField("jobLabel")}
//           placeholder="e.g. Primary job"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Pay period (month)" required>
//         <input
//           type="month"
//           value={manualForm.month}
//           onChange={updateManualField("month")}
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Tax code" required>
//         <input
//           type="text"
//           value={manualForm.taxCode}
//           onChange={updateManualField("taxCode")}
//           placeholder="e.g. 1257L"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Gross pay (£)" required>
//         <input
//           type="number"
//           step="0.01"
//           min="0"
//           value={manualForm.grossPay}
//           onChange={updateManualField("grossPay")}
//           placeholder="0.00"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Net take-home (£)" required>
//         <input
//           type="number"
//           step="0.01"
//           min="0"
//           value={manualForm.netPay}
//           onChange={updateManualField("netPay")}
//           placeholder="0.00"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Income tax (£)" required>
//         <input
//           type="number"
//           step="0.01"
//           min="0"
//           value={manualForm.incomeTax}
//           onChange={updateManualField("incomeTax")}
//           placeholder="0.00"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="National Insurance (£)" required>
//         <input
//           type="number"
//           step="0.01"
//           min="0"
//           value={manualForm.nationalInsurance}
//           onChange={updateManualField("nationalInsurance")}
//           placeholder="0.00"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Pension contribution (£)">
//         <input
//           type="number"
//           step="0.01"
//           min="0"
//           value={manualForm.pensionContribution}
//           onChange={updateManualField("pensionContribution")}
//           placeholder="0.00"
//           className={inputClass}
//         />
//       </Field>

//       <Field label="Hourly rate (£)">
//         <input
//           type="number"
//           step="0.01"
//           min="0"
//           value={manualForm.hourlyRate}
//           onChange={updateManualField("hourlyRate")}
//           placeholder="0.00"
//           className={inputClass}
//         />
//       </Field>

//       <div className="flex flex-col gap-2 mt-2 pb-6">
//         <button
//           type="submit"
//           disabled={!canSubmitManual}
//           className="w-full py-3 bg-[#FFAE34] text-[#0d1410] text-xs font-bold rounded-xl tracking-wide uppercase transition-opacity disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
//         >
//           Save payslip
//         </button>

//         <button
//           type="button"
//           onClick={resetToFilePicker}
//           className="w-full py-2.5 bg-transparent text-[var(--sage)] hover:text-[var(--ink)] text-xs text-center font-medium transition-colors border-0 cursor-pointer"
//         >
//           ← Back to file upload
//         </button>
//       </div>
//     </form>
//   );

//   // ─── Render ───────────────────────────────────────────────────────────────
//   return (
//     <PrototypeScaffold step={0} nextHref="#" backHref="/">
//       {() => (
//         <div className="basis-screen active relative h-full flex flex-col pt-4 overflow-y-auto custom-scrollbar text-[var(--ink)]">
//           <PageHeader title={manualMode ? "Manual entry" : "Add payslip"} />

//           {manualMode ? <ManualView /> : <UploadView />}
//         </div>
//       )}
//     </PrototypeScaffold>
//   );
// }


"use client";

import { useRef, useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
import { parsePayslipPdf, createManualPayslip } from "@/lib/parse-pdf";
import type { ManualPayslipInput } from "@/lib/parse-pdf";
import type { Payslip } from "@/app/Types/Types";

// ─── Constants ────────────────────────────────────────────────────────────

const STORAGE_KEY = "slyp:payslips";

const EMPTY_MANUAL_FORM: ManualPayslipInput & {
  month: string;
  jobLabel: string;
  hours: string;
} = {
  jobLabel: "Primary job",
  month: new Date().toISOString().slice(0, 7),
  grossPay: "",
  incomeTax: "",
  nationalInsurance: "",
  pensionContribution: "",
  netPay: "",
  taxCode: "",
  hourlyRate: "",
  hours: "",
};

const SWEEP_STEPS = [
  "Hourly rate",
  "Gross salary",
  "Income tax",
  "National Insurance",
  "Net take-home",
];

const INPUT_CLASS =
  "w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34] transition-colors";

// ─── Stable Field component (must be outside page to avoid focus-loss) ────

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium">
        {label}
        {required && <span className="text-[#FFAE34] ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────

export default function UploadPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [jobLabel, setJobLabel] = useState("Primary job");
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [manualMode, setManualMode] = useState(false);
  const [manualForm, setManualForm] = useState(EMPTY_MANUAL_FORM);
  const [uploadedFileName, setUploadedFileName] = useState("");
  const [sweepIndex, setSweepIndex] = useState(0);

  useEffect(() => {
    void searchParams.get("source"); // "camera" if needed later
  }, [searchParams]);

  // Sweep animation during processing
  useEffect(() => {
    if (!isUploading) return;
    setSweepIndex(0);
    const interval = setInterval(() => {
      setSweepIndex((prev) => {
        if (prev >= SWEEP_STEPS.length) {
          clearInterval(interval);
          return SWEEP_STEPS.length;
        }
        return prev + 1;
      });
    }, 450);
    return () => clearInterval(interval);
  }, [isUploading]);

  // Required: jobLabel, grossPay, netPay, incomeTax, nationalInsurance, taxCode
  const canSubmitManual = useMemo(
    () =>
      Boolean(
        manualForm.jobLabel.trim() &&
          manualForm.grossPay &&
          manualForm.netPay &&
          manualForm.incomeTax &&
          manualForm.nationalInsurance &&
          manualForm.taxCode.trim()
      ),
    [manualForm]
  );

  const updateField =
    (field: keyof typeof EMPTY_MANUAL_FORM) =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setManualForm((curr) => ({ ...curr, [field]: e.target.value }));

  const savePayslip = (payslip: Payslip) => {
    const raw = localStorage.getItem(STORAGE_KEY);
    const existing: Payslip[] = raw ? JSON.parse(raw) : [];
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...existing, payslip]));
    setMessage(null);
    setManualMode(false);
    setManualForm(EMPTY_MANUAL_FORM);
    router.push("/");
  };

  const handleNativeFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadedFileName(file.name);
    setSweepIndex(0);
    executeUpload(file);
  };

  const executeUpload = async (file: File) => {
    setIsUploading(true);
    setMessage(null);

    try {
      // parsePayslipPdf returns ParseResult: { success, payslip, missingFields, confidence }
      const result = await parsePayslipPdf(file, jobLabel || "Primary job");

      if (result.success && result.payslip) {
        savePayslip(result.payslip);
        return;
      }

      // Partial extraction — pre-fill whatever was read and switch to manual
      setManualForm({
        ...EMPTY_MANUAL_FORM,
        jobLabel: jobLabel || "Primary job",
        // payslip is null on failure, so fall back to empty strings
        grossPay: result.payslip?.grossPay?.toString() ?? "",
        netPay: result.payslip?.netPay?.toString() ?? "",
        incomeTax: result.payslip?.incomeTax?.toString() ?? "",
        nationalInsurance: result.payslip?.nationalInsurance?.toString() ?? "",
        pensionContribution: result.payslip?.pensionContribution?.toString() ?? "",
        taxCode: result.payslip?.taxCode ?? "",
        hourlyRate: result.payslip?.hourlyRate?.toString() ?? "",
        month: result.payslip?.month ?? new Date().toISOString().slice(0, 7),
      });

      const missingLabels: Record<string, string> = {
        grossPay: "gross pay",
        incomeTax: "income tax",
        nationalInsurance: "National Insurance",
        netPay: "net pay",
        taxCode: "tax code",
      };
      const missingNames = result.missingFields
        .map((f) => missingLabels[f] ?? f)
        .join(", ");

      setManualMode(true);
      setMessage(
        missingNames
          ? `Couldn't read: ${missingNames}. Fill in the missing fields below.`
          : "Some values couldn't be confirmed. Check the fields below."
      );
    } catch (error) {
      setManualMode(true);
      setMessage(
        error instanceof Error
          ? error.message
          : "Couldn't parse this PDF. Enter the values manually below."
      );
    } finally {
      setIsUploading(false);
    }
  };

  const handleManualSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    try {
      // createManualPayslip expects a flat ManualPayslipInput — no nested deductions
      const payslip = createManualPayslip({
        jobLabel: manualForm.jobLabel || "Primary job",
        month: manualForm.month || new Date().toISOString().slice(0, 7),
        grossPay: manualForm.grossPay,
        incomeTax: manualForm.incomeTax,
        nationalInsurance: manualForm.nationalInsurance,
        pensionContribution: manualForm.pensionContribution || 0,
        netPay: manualForm.netPay,
        taxCode: manualForm.taxCode,
        hourlyRate: manualForm.hourlyRate || null,
      });
      savePayslip(payslip);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Please complete all required fields."
      );
    }
  };

  const resetToFilePicker = () => {
    setManualMode(false);
    setMessage(null);
    setUploadedFileName("");
    setSweepIndex(0);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ─── Render ───────────────────────────────────────────────────────────────

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
              {manualMode ? "Manual entry" : "Add payslip"}
            </h1>
            <div className="w-4 opacity-0" aria-hidden="true">‹</div>
          </div>

          {/* ── Upload view ── */}
          {!manualMode && (
            <div className="flex flex-col flex-1">
              <input
                id="payslip"
                name="payslip"
                type="file"
                ref={fileInputRef}
                onChange={handleNativeFileChange}
                accept="application/pdf"
                className="hidden"
              />

              {!isUploading && !uploadedFileName ? (
                <>
                  <div className="mb-4">
                    <Field label="Job label">
                      <input
                        type="text"
                        value={jobLabel}
                        onChange={(e) => setJobLabel(e.target.value)}
                        placeholder="e.g. Primary job, Freelance"
                        className={INPUT_CLASS}
                      />
                    </Field>
                  </div>

                  <div className="relative w-full overflow-hidden rounded-2xl flex flex-col items-center justify-center">
                    <div className="absolute left-0 right-0 h-[4px] bg-[#d6a459] pointer-events-none z-40 shadow-[0_0_30px_#FFAE34,0_0_6px_#FFAE34] animate-yellow-laser" />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="w-full bg-[#34423d] border border-[#515a57] rounded-3xl p-8 transition-all flex flex-col items-center justify-center gap-4 cursor-pointer py-16 shadow-xs hover:border-[#FFAE34]/40"
                    >
                      <span className="text-3xl">📄</span>
                      <div className="text-[var(--ink)] text-xs font-bold uppercase tracking-wider">
                        Upload PDF payslip
                      </div>
                      <div className="text-[var(--ink)] text-[10px] text-center px-2 leading-relaxed opacity-60">
                        Select a digital PDF to extract your data automatically.
                      </div>
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => setManualMode(true)}
                    className="mt-6 w-full text-center text-[var(--sage)] hover:text-[var(--ink)] font-medium text-xs py-2 transition-colors cursor-pointer bg-transparent border-0"
                  >
                    Enter values manually instead →
                  </button>
                </>
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
                    {SWEEP_STEPS.map((stepLabel, i) => {
                      const active = sweepIndex > i;
                      return (
                        <div
                          key={stepLabel}
                          className={`text-[11px] px-3 py-2 rounded-xl border transition-all duration-200 ${
                            active
                              ? "bg-[var(--surface-2)] border-[var(--ink)]"
                              : "border-[var(--border)] opacity-30"
                          }`}
                        >
                          {active ? "✓" : "•"} {stepLabel}:{" "}
                          {active
                            ? i < SWEEP_STEPS.length - 1
                              ? "Processing…"
                              : "Analyzing…"
                            : "Waiting…"}
                        </div>
                      );
                    })}
                  </div>

                  {message && (
                    <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-xl px-3 py-2.5 text-[11px] text-[#FFAE34] mb-4">
                      ⚠️ {message}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Manual entry view ── */}
          {manualMode && (
            <form onSubmit={handleManualSubmit} className="flex flex-col gap-4 flex-1">
              {message && (
                <div className="w-full bg-[#2a1f0e] border border-[#FFAE34]/40 rounded-xl px-3 py-2.5 text-[11px] text-[#FFAE34]">
                  ⚠️ {message}
                </div>
              )}

              <Field label="Job label" required>
                <input
                  type="text"
                  value={manualForm.jobLabel}
                  onChange={updateField("jobLabel")}
                  placeholder="e.g. Primary job"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Pay period (month)" required>
                <input
                  type="month"
                  value={manualForm.month}
                  onChange={updateField("month")}
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Tax code" required>
                <input
                  type="text"
                  value={String(manualForm.taxCode)}
                  onChange={updateField("taxCode")}
                  placeholder="e.g. 1257L"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Gross pay (£)" required>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={manualForm.grossPay}
                  onChange={updateField("grossPay")}
                  placeholder="0.00"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Net take-home (£)" required>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={manualForm.netPay}
                  onChange={updateField("netPay")}
                  placeholder="0.00"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Income tax (£)" required>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={manualForm.incomeTax}
                  onChange={updateField("incomeTax")}
                  placeholder="0.00"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="National Insurance (£)" required>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={manualForm.nationalInsurance}
                  onChange={updateField("nationalInsurance")}
                  placeholder="0.00"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Pension contribution (£)">
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={manualForm.pensionContribution}
                  onChange={updateField("pensionContribution")}
                  placeholder="0.00"
                  className={INPUT_CLASS}
                />
              </Field>

              <Field label="Hourly rate (£)">
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={String(manualForm.hourlyRate ?? "")}
                  onChange={updateField("hourlyRate")}
                  placeholder="0.00"
                  className={INPUT_CLASS}
                />
              </Field>

              <div className="flex flex-col gap-2 mt-2 pb-6">
                <button
                  type="submit"
                  disabled={!canSubmitManual}
                  className="w-full py-3 bg-[#FFAE34] text-[#0d1410] text-xs font-bold rounded-xl tracking-wide uppercase transition-opacity disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                >
                  Continue →
                </button>

                <button
                  type="button"
                  onClick={resetToFilePicker}
                  className="w-full py-2.5 bg-transparent text-[var(--sage)] hover:text-[var(--ink)] text-xs text-center font-medium transition-colors border-0 cursor-pointer"
                >
                  ← Back to file upload
                </button>
              </div>
            </form>
          )}

        </div>
      )}
    </PrototypeScaffold>
  );
}