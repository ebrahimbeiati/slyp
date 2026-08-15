"use client";

import { useEffect, ReactNode } from "react";

interface BottomSheetProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly title: string;
  readonly children: ReactNode;
}

export function BottomSheet({ isOpen, onClose, title, children }: BottomSheetProps) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "unset";
    }
    return () => {
      document.body.style.overflow = "unset";
    };
  }, [isOpen]);

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 transition-colors"
          style={{ backgroundColor: "rgba(6, 16, 12, 0.62)" }}
          onClick={onClose}
        />
      )}

      <div
        className="fixed left-0 right-0 bottom-0 z-50 transition-transform rounded-t-5xl"
        style={{
          backgroundColor: "var(--surface-2)",
          borderColor: "rgba(243, 246, 242, 0.08)",
          transform: isOpen ? "translateY(0)" : "translateY(100%)",
          borderTopWidth: "1px",
        }}
      >
        <div className="px-6 pt-3 pb-4">
          <div className="w-8 h-1 rounded bg-center mx-auto" style={{ backgroundColor: "rgba(243, 246, 242, 0.08)" }} />
        </div>

        <div className="px-6 pb-8 max-h-96 overflow-y-auto">
          <h3 className="text-lg font-semibold mb-4" style={{ color: "var(--ink)" }}>
            {title}
          </h3>
          {children}
        </div>
      </div>
    </>
  );
}
