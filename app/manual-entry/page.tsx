"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";
import type { PayFrequency, StudentLoanPlan, TaxRegion } from "@/lib/Api";

const STORAGE_KEY = "slyp:payslips";

export default function ManualEntryPage() {
  const router = useRouter();

  // Form State Vectors
  const [jobLabel, setJobLabel] = useState("");
  const [month, setMonth] = useState("August");
  const [taxCode, setTaxCode] = useState("1257L");
  const [frequency, setFrequency] = useState<PayFrequency>("MONTHLY");
  const [region, setRegion] = useState<TaxRegion>("UK_STANDARD");
  const [studentLoanPlan, setStudentLoanPlan] = useState<StudentLoanPlan>("NONE");
  const [grossPay, setGrossPay] = useState("");
  const [netPay, setNetPay] = useState("");

  const [error, setError] = useState<string | null>(null);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const grossNum = parseFloat(grossPay);
    const netNum = parseFloat(netPay);

    if (!jobLabel.trim()) {
      setError("Please specify a job title or employer name.");
      return;
    }
    if (isNaN(grossNum) || grossNum <= 0 || isNaN(netNum) || netNum <= 0) {
      setError("Please enter valid positive values for Gross and Net pay.");
      return;
    }
    if (netNum > grossNum) {
      setError("Net pay cannot be higher than your gross pay. Please check your figures.");
      return;
    }

    // Auto prepend Scotland region taxonomy if they missed it inside the text field string
    let verifiedTaxCode = taxCode.trim().toUpperCase();
    if (region === "SCOTLAND" && !verifiedTaxCode.startsWith("S") && !["BR", "0T"].includes(verifiedTaxCode)) {
      verifiedTaxCode = "S" + verifiedTaxCode;
    }

    const newPayslip = {
      id: `manual_${Date.now()}`,
      jobLabel: jobLabel.trim(),
      month,
      taxCode: verifiedTaxCode,
      frequency,
      region,
      studentLoanPlan,
      netPay: netNum,
      grossPay: grossNum,
    };

    if (typeof window !== "undefined") {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const existingData = raw ? JSON.parse(raw) : [];
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...existingData, newPayslip]));
      } catch (err) {
        console.error("Storage system execution error", err);
      }
    }

    router.push("/");
  };

  return (
    <PrototypeScaffold
      step={1}
      nextHref="/"
      annotation={{
        number: "03 · Advanced UK Payroll Form",
        title: "Demographic Tax Edgecases",
        description:
          "Dynamically matches user demographics like pay intervals, Scottish brackets, and specific Student loan bands prior to committing parameters.",
      }}
    >
      {() => (
        <div className="basis-screen active relative h-full flex flex-col pt-4 overflow-y-auto custom-scrollbar">
          <div className="flex justify-between items-center mb-6 shrink-0">
            <Link href="/" className="text-gray-400 hover:text-white text-sm focus:outline-none">‹</Link>
            <h1 className="text-white text-sm font-semibold tracking-tight">Tax Input Configuration</h1>
            <div className="w-4 opacity-0">‹</div>
          </div>

          <form onSubmit={handleSave} className="flex flex-col gap-3.5 flex-1 pb-4">
            
            {/* Field: Employer Label */}
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Employer name</label>
              <input 
                type="text" 
                value={jobLabel} 
                onChange={(e) => setJobLabel(e.target.value)} 
                placeholder="e.g. Acme Tech Group"
                className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34] placeholder-gray-700 font-medium"
              />
            </div>

            {/* Grid Row: Pay Interval Frequency & Regional Jurisdiction */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Pay Frequency</label>
                <select
                  value={frequency}
                  onChange={(e) => setFrequency(e.target.value as PayFrequency)}
                  className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3 text-xs focus:outline-none focus:border-[#FFAE34] font-medium"
                >
                  <option value="MONTHLY">Monthly cycle</option>
                  <option value="WEEKLY">Weekly cycle</option>
                  <option value="FORTNIGHTLY">Fortnightly</option>
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Jurisdiction Region</label>
                <select
                  value={region}
                  onChange={(e) => setRegion(e.target.value as TaxRegion)}
                  className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3 text-xs focus:outline-none focus:border-[#FFAE34] font-medium"
                >
                  <option value="UK_STANDARD">England / Wales / NI</option>
                  <option value="SCOTLAND">Scotland (S-Code)</option>
                </select>
              </div>
            </div>

            {/* Grid Row: Target Processing Month & Base Tax Code String */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Pay Period Month</label>
                <select value={month} onChange={(e) => setMonth(e.target.value)} className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3 text-xs focus:outline-none focus:border-[#FFAE34] font-medium">
                  <option value="August">August</option>
                  <option value="September">September</option>
                  <option value="October">October</option>
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Tax Code</label>
                <input 
                  type="text" 
                  value={taxCode} 
                  onChange={(e) => setTaxCode(e.target.value)} 
                  placeholder="e.g. 1257L"
                  className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3.5 text-xs focus:outline-none focus:border-[#FFAE34] placeholder-gray-700 font-mono uppercase font-medium"
                />
              </div>
            </div>

            {/* Field: Student Loan Allocation Selector */}
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Student Loan Repayment Scheme</label>
              <select
                value={studentLoanPlan}
                onChange={(e) => setStudentLoanPlan(e.target.value as StudentLoanPlan)}
                className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 px-3 text-xs focus:outline-none focus:border-[#FFAE34] font-medium"
              >
                <option value="NONE">No outstanding student loan liabilities</option>
                <option value="PLAN_1">Plan 1 (Pre-2012 / Northern Ireland)</option>
                <option value="PLAN_2">Plan 2 (England / Wales 2012-2023)</option>
                <option value="PLAN_4">Plan 4 (Scottish Student Loans)</option>
                <option value="PLAN_5">Plan 5 (Undergrad courses post-August 2023)</option>
                <option value="POSTGRAD">Postgraduate Loan (Separate 6% scale)</option>
              </select>
            </div>
            {/* Grid Row: Money Currency Gross & Net Input Values */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Gross Pay (This period)</label>
                <div className="relative">
                  <span className="absolute left-3 top-[9px] text-gray-600 text-xs font-medium">£</span>
                  <input 
                    type="number" 
                    step="0.01" 
                    value={grossPay} 
                    onChange={(e) => setGrossPay(e.target.value)} 
                    placeholder="2500" 
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 pl-6 pr-3 text-xs focus:outline-none focus:border-[#FFAE34] font-medium" 
                  />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-gray-500 text-[9px] font-medium uppercase tracking-wider">Net Take-Home</label>
                <div className="relative">
                  <span className="absolute left-3 top-[9px] text-gray-600 text-xs font-medium">£</span>
                  <input 
                    type="number" 
                    step="0.01" 
                    value={netPay} 
                    onChange={(e) => setNetPay(e.target.value)} 
                    placeholder="1842" 
                    className="w-full bg-[#141A17] border border-[#232D27] text-white rounded-xl py-2.5 pl-6 pr-3 text-xs focus:outline-none focus:border-[#FFAE34] font-medium" 
                  />
                </div>
              </div>
            </div>

            {/* Error Message Section */}
            {error && (
              <div className="text-red-400 bg-red-950/20 border border-red-900/40 rounded-xl p-3 text-[10px] leading-relaxed font-mono mt-1 animate-fadeIn">
                ⚠️ Verification Error: {error}
              </div>
            )}

            {/* Form Button Action Footer */}
            <div className="mt-auto pt-4 shrink-0">
              <button
                type="submit"
                className="w-full py-3 bg-[#FFAE34] hover:bg-[#FFC166] text-[#141A17] font-bold rounded-xl transition-colors duration-150 cursor-pointer"
              >
                Save Advanced Parameters
              </button>
              <Link 
                href="/" 
                className="block w-full py-3 bg-transparent border border-[#232D27] text-gray-400 hover:text-white rounded-xl text-xs text-center font-medium transition-colors mt-2"
              >
                Cancel
              </Link>
            </div>
          </form>
        </div>
      )}
    </PrototypeScaffold>
  );
}
