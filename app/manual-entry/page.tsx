"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";

export default function ManualEntryPage() {
  const router = useRouter();
  const [jobLabel, setJobLabel] = useState("");
  const [taxCode, setTaxCode] = useState("1257L");
  const [grossPay, setGrossPay] = useState("");
  const [netPay, setNetPay] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSaveForm = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const grossNum = parseFloat(grossPay);
    const netNum = parseFloat(netPay);

    if (!jobLabel.trim()) { setError("Employer name required."); return; }
    if (isNaN(grossNum) || isNaN(netNum) || netNum > grossNum) { setError("Net pay cannot exceed gross salary totals."); return; }

    const manualExtract = {
      employer_name: jobLabel.trim(),
      tax_code: { value: taxCode.trim().toUpperCase() },
      pay: { hourly_rate: "12.50", hours: "40.0", gross_this_period: grossNum.toFixed(2) },
      deductions: { income_tax: (grossNum - netNum).toFixed(2), national_insurance: "0.00" },
      net_pay: netNum.toFixed(2)
    };

    if (typeof window !== "undefined") {
      localStorage.setItem("slyp:payslips", JSON.stringify([manualExtract]));
    }
    router.push("/");
  };

  return (
    <PrototypeScaffold step={0} nextHref="#" backHref="/">
      {() => (
        <div className="basis-screen active relative h-full flex flex-col pt-4 overflow-y-auto custom-scrollbar font-mono text-xs text-[var(--ink)]">
          <div className="flex justify-between items-center mb-6 shrink-0">
            <Link href="/" className="text-[var(--sage)] hover:text-[var(--ink)] text-lg font-bold">‹</Link>
            <h1 className="text-white text-xs font-bold uppercase tracking-wider">Input Payslip</h1>
            <div className="w-4 opacity-0">‹</div>
          </div>

          <form onSubmit={handleSaveForm} className="flex flex-col gap-3.5 flex-1 pb-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[var(--sage)] text-[9px] uppercase tracking-wider">Your Name</label>
              <input type="text" value={jobLabel} onChange={(e) => setJobLabel(e.target.value)} placeholder="e.g. Fox & Hound" className="w-full bg-[var(--surface-2)] border border-[var(--border)] text-white rounded-xl py-2.5 px-3.5 focus:outline-none" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-[var(--sage)] text-[9px] uppercase tracking-wider">Tax Code</label>
                <input type="text" value={taxCode} onChange={(e) => setTaxCode(e.target.value)} className="w-full bg-[var(--surface-2)] border border-[var(--border)] text-white rounded-xl py-2.5 px-3.5 focus:outline-none uppercase font-bold" />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[var(--sage)] text-[9px] uppercase tracking-wider">Gross Pay (£)</label>
                <input type="number" step="0.01" value={grossPay} onChange={(e) => setGrossPay(e.target.value)} placeholder="2430" className="w-full bg-[var(--surface-2)] border border-[var(--border)] text-white rounded-xl py-2.5 px-3.5 focus:outline-none font-bold" />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-[var(--sage)] text-[9px] uppercase tracking-wider">Net Take-Home Pay</label>
              <input type="number" step="0.01" value={netPay} onChange={(e) => setNetPay(e.target.value)} placeholder="1842" className="w-full bg-[var(--surface-2)] border border-[var(--border)] text-white rounded-xl py-2.5 px-3.5 focus:outline-none font-bold text-[var(--amber)]" />
            </div>

            {error && <div className="text-red-400 bg-red-950/20 border border-red-900/40 rounded-xl p-3 text-[10px]">⚠️ Error: {error}</div>}

            <div className="mt-auto pt-4 shrink-0">
              <button type="submit" className="w-full py-3 bg-[var(--amber)] text-black font-bold rounded-xl text-xs uppercase tracking-widest border-0 cursor-pointer">
                Save Parameters
              </button>
            </div>
          </form>
        </div>
      )}
    </PrototypeScaffold>
  );
}
