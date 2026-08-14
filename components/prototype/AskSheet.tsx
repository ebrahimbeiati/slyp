"use client";

import { useState } from "react";
import { MOCK_QA_DATA } from "@/app/data/mockQuestions"; // 👈 Adjust path based on where you created the file

interface AskSheetProps {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}

export function AskSheet({ open, onClose }: AskSheetProps) {
  const [selectedQA, setSelectedQA] = useState<{ question: string; answer: string } | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleQuestionTap = (q: string, a: string) => {
    setIsLoading(true);
    setSelectedQA(null);

    setTimeout(() => {
      setSelectedQA({ question: q, answer: a });
      setIsLoading(false);
    }, 600);
  };

  const handleReset = () => {
    setSelectedQA(null);
  };

  const handleClosePanel = () => {
    setSelectedQA(null);
    onClose();
  };

  return (
    <>
      {/* Animated Backdrop Scrim */}
      <button
        type="button"
        onClick={handleClosePanel}
        className={`fixed inset-0 bg-black/70 backdrop-blur-xs transition-opacity duration-300 z-50 ${
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        }`}
        aria-label="Close question layer"
      />

      {/* Slide-Up Mobile Viewport Drawer Panel */}
      <div
        className={`fixed bottom-0 left-0 right-0 max-w-sm mx-auto bg-[#0F1412] border-t border-[#222B26] rounded-t-3xl p-6 pb-10 transition-transform duration-400 ease-out z-50 flex flex-col h-[75vh] transform ${
          open ? "translate-y-0" : "translate-y-full"
        }`}
      >
        {/* Visual Handle Accent */}
        <div className="w-12 h-1.5 bg-[#25302A] rounded-full mx-auto mb-6 shrink-0" />
        
        <div className="flex items-center gap-2 mb-2 shrink-0">
          <span className="text-[10px] font-mono uppercase bg-[#1B2621] text-[#FFAE34] px-2 py-0.5 rounded border border-[#2B3D34] tracking-wider">
            Slyp Copilot
          </span>
        </div>

        {/* Scrollable Container Content Section */}
        <div className="flex-1 overflow-y-auto pr-1 mb-4 custom-scrollbar">
          {!selectedQA && !isLoading ? (
            <div className="flex flex-col">
              <h3 className="text-white text-xl font-bold tracking-tight mb-2">Tap a question to inspect</h3>
              <p className="text-gray-400 text-xs mb-6 leading-relaxed">
                Skip the typing. Select one of our automated paycheck analysis macros to test your data pipelines instantly.
              </p>

              {/* Renders the full connected list of 10 items dynamically */}
              <div className="flex flex-col gap-2.5">
                {MOCK_QA_DATA.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleQuestionTap(item.question, item.answer)}
                    className="w-full text-left bg-[#161D1A] hover:bg-[#1E2723] border border-[#233029] hover:border-[#35483E] text-gray-200 text-xs font-medium p-4 rounded-xl transition-all active:scale-[0.99] cursor-pointer"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          ) : isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <div className="flex gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[#FFAE34] animate-bounce [animation-delay:-0.3s]" />
                <span className="w-2 h-2 rounded-full bg-[#FFAE34] animate-bounce [animation-delay:-0.15s]" />
                <span className="w-2 h-2 rounded-full bg-[#FFAE34] animate-bounce" />
              </div>
              <p className="text-gray-500 font-mono text-[11px] uppercase tracking-wider">Analyzing payslip rules...</p>
            </div>
          ) : (
            <div className="flex flex-col">
              <div className="bg-[#1B2320] border border-[#283530] p-3.5 rounded-xl rounded-br-none text-white text-xs mb-4 max-w-[90%] self-end">
                {selectedQA?.question}
              </div>

              <div className="bg-[#141C18] border border-[#1E2A24] p-4 rounded-xl rounded-bl-none text-gray-300 text-xs mb-6 leading-relaxed flex flex-col gap-2">
                <div className="text-[#FFAE34] font-mono text-[10px] tracking-wider uppercase mb-1">Response:</div>
                <p>{selectedQA?.answer}</p>
              </div>

              <button
                type="button"
                onClick={handleReset}
                className="text-[#FFAE34] hover:text-[#FFB648] text-xs font-medium self-start flex items-center gap-1 cursor-pointer"
              >
                ← Choose another question
              </button>
            </div>
          )}
        </div>

        {/* Global Footer Controls */}
        <div className="pt-3 border-t border-[#1D2622] shrink-0">
          <button
            type="button"
            onClick={handleClosePanel}
            className="w-full py-3 bg-transparent border border-[#26332C] hover:bg-[#151B18] text-gray-400 hover:text-white rounded-xl text-xs font-medium transition-colors cursor-pointer"
          >
            Close Copilot
          </button>
        </div>
      </div>
    </>
  );
}
