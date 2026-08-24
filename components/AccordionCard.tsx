"use client";

import { useState, type ReactNode } from "react";

/**
 * A collapsible card: always-visible header, body revealed on tap.
 *
 * Deliberately owns nothing but the open/closed state and the chevron.
 * Colour, borders, badges and every piece of copy come from the caller,
 * so the findings list keeps its severity styling exactly as it was and
 * the glossary can look different without this component knowing about
 * either.
 *
 * The body is conditionally rendered rather than animated open with a
 * max-height. A fixed max-height silently clips content taller than the
 * guess - and a finding's explanation is variable-length prose, which is
 * exactly the thing that would get cut off. The chevron still rotates,
 * so the interaction reads as an accordion without a layout trick that
 * can hide half a sentence on stage.
 */
export function AccordionCard({
  borderClass = "border-[var(--border)]",
  header,
  defaultOpen = false,
  children,
}: {
  /** Tailwind border class, so callers keep their own severity colours. */
  borderClass?: string;
  /** Always visible. Should carry enough to identify the card collapsed. */
  header: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      className={`w-full bg-[var(--surface-2)] border ${borderClass} rounded-2xl mb-3 overflow-hidden`}
    >
      <button
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        aria-expanded={open}
        className="w-full flex items-start gap-3 p-4 text-left bg-transparent border-0 cursor-pointer"
      >
        <div className="flex-1 min-w-0">{header}</div>
        <svg
          width="12"
          height="8"
          viewBox="0 0 12 8"
          fill="none"
          aria-hidden="true"
          className={`shrink-0 mt-1 text-[var(--sage)] transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        >
          <path
            d="M1 1l5 5 5-5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open && <div className="px-4 pb-4 -mt-1">{children}</div>}
    </div>
  );
}
