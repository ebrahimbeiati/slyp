"use client";

import Link from "next/link";
import { ReactNode } from "react";

interface ScaffoldProps {
  step: number;
  nextHref: string;
  backHref?: string; // 👈 FIXED: Added the "?" symbol to make this an optional string
  annotation: {
    number: string;
    title: string;
    description: string;
  };
  children: () => ReactNode;
}

export function PrototypeScaffold({ step, nextHref, backHref, annotation, children }: ScaffoldProps) {
  return (
    <div className="min-h-screen bg-[#090D0B] text-gray-200 flex flex-col items-center justify-start p-4 font-sans select-none">
      {/* Top Global Flow Controller Bar */}
      <div className="w-full max-w-md text-center mb-6 pt-2">
        <div className="text-[10px] text-gray-500 font-mono tracking-widest uppercase mb-3">
          BASIS — PAYSLIP & INCOME COMPANION · CLICK THROUGH THE FLOW
        </div>
        <div className="inline-flex bg-[#161C19] border border-[#232A26] rounded-full p-1 gap-1">
          <Link href="/" className={`px-4 py-1.5 rounded-full text-xs font-medium transition-colors ${step === 0 ? "bg-[#FFAE34] text-black" : "text-gray-400 hover:text-white"}`}>
            First payslip
          </Link>
          <Link href="/" className={`px-4 py-1.5 rounded-full text-xs font-medium transition-colors ${step === 1 ? "bg-[#FFAE34] text-black" : "text-gray-400 hover:text-white"}`}>
            After 4 payslips
          </Link>
        </div>
      </div>

      {/* Main Interactive Mobile Viewport Frame */}
      <div className="w-full max-w-sm bg-[#0D110F] border border-[#1C2420] rounded-[40px] p-6 shadow-2xl relative overflow-hidden aspect-[9/19] flex flex-col justify-between mb-6">
        {children()}
      </div>

      {/* Bottom Interactive Annotation Frame */}
      <div className="w-full max-w-sm bg-[#111614] border border-[#1E2522] rounded-2xl p-5 text-left font-mono">
        <div className="text-[#FFAE34] text-xs font-bold mb-1">{annotation.number}</div>
        <div className="text-white text-sm font-semibold mb-2">{annotation.title}</div>
        <div className="text-gray-400 text-xs leading-relaxed mb-4">{annotation.description}</div>
        
        {/* Navigation Buttons */}
        <div className="flex justify-between items-center border-t border-[#1C2420] pt-3">
          {/* FIXED: Check if backHref exists. If yes, render Link. If no, render disabled button to prevent 500 crashes */}
          {backHref ? (
            <Link 
              href={backHref} 
              className="text-gray-300 hover:text-white text-xs flex items-center gap-1 transition-colors font-medium"
            >
              ← Back
            </Link>
          ) : (
            <button 
              type="button"
              className="text-gray-600 text-xs flex items-center gap-1 cursor-not-allowed font-medium" 
              disabled
            >
              ← Back
            </button>
          )}

          <Link href={nextHref} className="bg-white hover:bg-gray-200 text-black text-xs font-semibold px-4 py-1.5 rounded-lg flex items-center gap-1 transition-colors">
            Next →
          </Link>
        </div>
      </div>
    </div>
  );
}
