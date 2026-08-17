"use client";

import Link from "next/link";
import { useState } from "react";
import { AskSheet } from "@/components/prototype/AskSheet";
import { PrototypeScaffold } from "@/components/prototype/PrototypeScaffold";

export default function HomePage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [askOpen, setAskOpen] = useState(false);

  return (
    <PrototypeScaffold
      step={0}
      nextHref="/upload"
      annotation={{
        number: "01 · Home, empty state",
        title: "Nothing to hide behind",
        description:
          "First open has no data to fake. One clear job: scan a payslip. Locked stats hint at what unlocks, without pretending they have values yet. The amber \"Ask\" button in the corner is always there if something is confusing before you've even scanned anything.",
      }}
    >
      {() => (
        <>
          <div className="basis-screen active relative pb-16">
            {/* Top Bar Greeting */}
            <div className="basis-topbar flex justify-between items-center mb-6">
              <div>
                <div className="basis-greet-eyebrow text-gray-400 text-sm font-light">Morning</div>
                <div className="basis-greet-name text-white text-2xl font-bold tracking-tight">Chen</div>
              </div>
              <div className="basis-avatar w-10 h-10 rounded-full bg-emerald-900/40 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-semibold">
                C
              </div>
            </div>

            {/* Empty State Hero Card */}
            <div className="basis-hero-card only-first bg-[#121B16] border border-[#1E2E25] rounded-2xl p-6 mb-6 flex flex-col items-start">
              <div className="basis-hero-icon w-10 h-10 rounded-lg bg-[#241F1A] border border-[#3D2F20] flex items-center justify-center mb-4">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M6 3h9l5 5v13a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z" stroke="#FFB648" strokeWidth="1.6" />
                  <path d="M9 12h6M9 16h6M9 8h2" stroke="#FFB648" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </div>
              <div className="basis-hero-title text-white text-lg font-semibold mb-1">Add your first payslip</div>
              <div className="basis-hero-sub text-gray-400 text-sm leading-relaxed mb-6">
                Takes about 20 seconds. We read the numbers, then forget the file.
              </div>
              <button 
                className="basis-btn-primary w-full py-3 bg-[#FFAE34] hover:bg-[#E59A2B] text-black font-medium rounded-xl transition-colors duration-150 text-center" 
                type="button" 
                onClick={() => setSheetOpen(true)}
              >
                Scan payslip
              </button>
            </div>

            {/* Locked Empty Stats Row */}
            <div className="basis-stat-row grid grid-cols-3 gap-3 mb-8">
              <div className="basis-stat locked only-first bg-[#111614] border border-dashed border-[#242A27] rounded-xl p-4">
                <div className="basis-stat-label text-gray-500 text-xs font-medium uppercase tracking-wider mb-2">Take-home</div>
                <div className="basis-stat-value text-gray-600 text-lg font-medium">- -</div>
              </div>
              <div className="basis-stat locked only-first bg-[#111614] border border-dashed border-[#242A27] rounded-xl p-4">
                <div className="basis-stat-label text-gray-500 text-xs font-medium uppercase tracking-wider mb-2">Tax paid</div>
                <div className="basis-stat-value text-gray-600 text-lg font-medium">- -</div>
              </div>
              <div className="basis-stat locked only-first bg-[#111614] border border-dashed border-[#242A27] rounded-xl p-4">
                <div className="basis-stat-label text-gray-500 text-xs font-medium uppercase tracking-wider mb-2">Pension</div>
                <div className="basis-stat-value text-gray-600 text-lg font-medium">- -</div>
              </div>
            </div>

            {/* Bottom Navigation */}
            <div className="basis-bottom-nav flex justify-around items-center border-t border-[#1C2420] pt-4 mt-auto">
              <div className="basis-nav-item active text-[#FFAE34] text-sm flex flex-col items-center gap-1 font-medium cursor-pointer">
                <span className="basis-nav-dot w-1.5 h-1.5 rounded-full bg-[#FFAE34]" />
                Home
              </div>
              <div className="basis-nav-item text-gray-500 text-sm font-medium cursor-pointer hover:text-gray-300">Insights</div>
              <div className="basis-nav-item text-gray-500 text-sm font-medium cursor-pointer hover:text-gray-300">You</div>
            </div>

          {/* Floating Action 'Ask' Button */}
<button
  type="button"
  onClick={() => setAskOpen(true)} // 👈 CHANGE THIS LINE HERE from setSheetOpen to setAskOpen
  className="absolute right-4 bottom-14 w-12 h-12 bg-[#FFAE34] hover:bg-[#E59A2B] text-black font-semibold text-lg rounded-full flex items-center justify-center shadow-lg shadow-black/40 transition-transform active:scale-95 focus:outline-none z-10"
  aria-label="Ask a question"
>
  ?
</button>


            {/* ACTION SHEET WRAPPER (Scrim + Slide-up container) */}
            <div>
              {/* Animated Backdrop Scrim */}
              <button 
                type="button" 
                className={`fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity ease-out duration-300 z-40 ${
                  sheetOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
                }`} 
                onClick={() => setSheetOpen(false)} 
                aria-label="Close sheet panel" 
              />
              
             {/* Eased Slide-Up Panel Content */}
<div 
  className={`fixed bottom-0 left-0 right-0 max-w-sm mx-auto bg-[#121614] border-t border-[#232A26] rounded-t-3xl px-6 pt-3 pb-8 z-50 flex flex-col transform transition-transform cubic-bezier(0.32, 0.94, 0.6, 1) duration-400 ${
    sheetOpen ? "translate-y-0" : "translate-y-full"
  }`}
>

                {/* Visual Handle Accent */}
                <div className="w-12 h-1.5 bg-[#2E3631] rounded-full mx-auto mb-6" />
                <div className="text-white text-xl font-semibold mb-4">Add your payslip</div>
                
                <Link 
                  className="flex items-center gap-4 bg-[#1A201D] hover:bg-[#232A26] border border-[#2A332E] text-white p-4 rounded-xl mb-3 font-medium transition-colors duration-150" 
                  href="/upload" 
                  onClick={() => setSheetOpen(false)}
                >
                  <span className="text-xl">📷</span>
                  Take a photo
                </Link>
                
                <Link 
                  className="flex items-center gap-4 bg-[#1A201D] hover:bg-[#232A26] border border-[#2A332E] text-white p-4 rounded-xl mb-6 font-medium transition-colors duration-150" 
                  href="/upload" 
                  onClick={() => setSheetOpen(false)}
                >
                  <span className="text-xl">📄</span>
                  Upload PDF
                </Link>
                 {/* NEW: VISUAL MANUAL OPTION INJECTED SECURELY HERE */}
  <Link 
    className="flex items-center gap-4 bg-[#1A201D] hover:bg-[#232A26] border border-[#2A332E] text-white p-4 rounded-xl mb-6 font-medium transition-colors" 
    href="/manual-entry" // 👈 Points to your upcoming form wizard
    onClick={() => setSheetOpen(false)}
  >
    <span className="text-xl">✍️</span>
    Enter figures manually
  </Link>
                
                <div className="text-xs text-gray-500 leading-relaxed mb-6">
                  🔒 Read on your device. The original file is deleted the moment we pull out the numbers. We only keep totals.
                </div>
                
                <button 
                  className="w-full py-3 bg-transparent border border-[#2A332E] text-gray-400 hover:text-white font-medium rounded-xl transition-colors duration-150" 
                  type="button" 
                  onClick={() => setSheetOpen(false)}
                >
                  Cancel
                </button>
              </div>
            </div>

          </div>

          <AskSheet open={askOpen} onOpen={() => setAskOpen(true)} onClose={() => setAskOpen(false)} />
        </>
      )}
    </PrototypeScaffold>
  );
}
