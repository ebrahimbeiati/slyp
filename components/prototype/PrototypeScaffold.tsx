"use client";

import Link from "next/link";
import { useState, useEffect, ReactNode } from "react";

interface ScaffoldProps {
  step: number;
  nextHref: string;
  backHref?: string;
  children: () => ReactNode;
}

export function PrototypeScaffold({ step, nextHref, backHref, children }: ScaffoldProps) {
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedTheme = localStorage.getItem("slyp:theme");
      // Default to dark mode if no previous preference is recorded
      const darkActive = savedTheme ? savedTheme === "dark" : true;
      
      // FIXED: Deferred state assignment to prevent cascading render layout warnings
      requestAnimationFrame(() => {
        setIsDark(darkActive);
        
        if (darkActive) {
          document.documentElement.classList.add("dark");
        } else {
          document.documentElement.classList.remove("dark");
        }
      });
    }
  }, []);


  const handleToggleTheme = () => {
    const nextDark = !isDark;
    setIsDark(nextDark);
    
    if (typeof window !== "undefined") {
      localStorage.setItem("slyp:theme", nextDark ? "dark" : "light");
      if (nextDark) {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg-deep)] text-[var(--ink)] flex flex-col items-center justify-start p-4 font-mono select-none transition-colors duration-300 w-full">
      
      {/* Top Global Flow Controller Bar */}
      <div className="w-full max-w-md text-center mb-6 pt-2 flex flex-col items-center gap-3">
      
        <div className="flex items-center gap-3 justify-center">
          <div className="inline-flex bg-[var(--surface-2)] border border-[var(--border)] rounded-full p-1 gap-1 shadow-sm">
            <Link href="/" className={`px-4 py-2 rounded-3xl text-xs font-bold transition-colors bg-[#FFAE34] hover:bg-[#E59A2B] text-black font-bold" : "text-gray-400 hover:text-[var(--ink)]"}`}>
              First payslip
            </Link>
            <Link href="#" onClick={(e) => { e.preventDefault(); alert("🔒 Premium Tier\n\nMulti-payslip timelines require an upgraded active subscription."); }} className="px-4 py-1.5 rounded-full text-xs font-medium text-gray-500 hover:text-[var(--amber)]">
              After 4 payslips
            </Link>
          </div>
          
          {/* Native Inline Mode Toggle Button Trigger */}
          <button 
            type="button" 
            onClick={handleToggleTheme} 
            className="px-3 py-1.5 rounded-full bg-[var(--surface)] border border-[var(--border)] text-[var(--ink)] text-xs font-medium cursor-pointer shadow-sm min-w-[76px] hover:opacity-90 active:scale-95 transition-all"
          >
            {isDark ? "☀️ Light" : "🌙 Dark"}
          </button>
        </div>
      </div>

      {/* Main Interactive Mobile Viewport Frame */}
      <div className="w-full max-w-sm bg-[var(--surface)] border border-[var(--border)] rounded-[40px] p-6 shadow-2xl relative overflow-hidden aspect-[9/19] flex flex-col justify-between mb-6 transition-colors duration-300">
        {children()}
      </div>

      {/* Navigation Footers positioned outside phone layout frame */}
      <div className="w-full max-w-sm flex justify-between items-center px-4 pt-1">
        {backHref ? (
          <Link href={backHref} className="bg-[var(--ink)] text-[var(--surface)] hover:text-[var(--ink)] text-xs font-bold rounded-lg px-4 py-2">← Back</Link>
        ) : (
          <button type="button" className="bg-[var(--ink)] text-[var(--surface)] opacity-30 text-xs font-bold px-4 py-2 rounded-lg cursor-not-allowed" disabled>← Back</button>
        )}
        <Link href={nextHref} className="bg-[var(--ink)] text-[var(--surface)] hover:opacity-90 text-xs font-bold px-4 py-2 rounded-lg shadow-sm">Next →</Link>
      </div>
    </div>
  );
}
