"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Shows the payroll message before it is copied.
 *
 * A preview, not a receipt. The button that opens this does NOT copy -
 * the point is that someone can read what they are about to send to their
 * employer before they send it. Copying first and confirming afterwards
 * gets that backwards.
 *
 * WHY THIS IS A VIEWPORT OVERLAY AND NOT A CARD INSIDE THE PHONE FRAME.
 * Every other modal in this app is `absolute inset-0` within the mock
 * phone, which is max-w-sm (384px) and aspect-[9/19] - so about 810px
 * tall, already taller than a 1280x720 viewport, with the page scrolling
 * to accommodate it. A panel constrained to that would be 384px wide and
 * would itself need page-scrolling to read. This message is a document
 * the user is about to send, and it has to be legible from the back of a
 * room, so it takes the whole viewport instead.
 *
 * WHAT IS ON SCREEN IS WHAT IS COPIED. `message` is rendered as a single
 * text node with whitespace-pre-wrap and handed to the clipboard
 * unchanged - no trim, no replace, no join, no per-line mapping. Both the
 * <div> and writeText() read the same const. Pinned by
 * verify/final_payroll_preview.test.tsx, which server-renders this panel
 * and compares its text content to buildPayrollMessage() byte-for-byte.
 *
 * Exported separately from the portalled wrapper below precisely so that
 * check is possible: a portal cannot be server-rendered.
 */
export function PayrollPreviewPanel({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");
  const closeRef = useRef<HTMLButtonElement>(null);

  // Escape closes. Registered on the document rather than the panel so it
  // works before anything inside has been focused.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // Hold the page still while the panel is open, so closing it returns to
  // exactly the view it opened over.
  //
  // overflow:hidden alone would reclaim the scrollbar's width and shift
  // the layout underneath by ~15px - visible, and precisely the "must not
  // shift" this is meant to avoid. The padding compensates for it.
  // scrollTop is untouched throughout, so nothing moves vertically either.
  useEffect(() => {
    const { body, documentElement } = document;
    const scrollbar = window.innerWidth - documentElement.clientWidth;
    const previousOverflow = body.style.overflow;
    const previousPadding = body.style.paddingRight;

    body.style.overflow = "hidden";
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`;

    return () => {
      body.style.overflow = previousOverflow;
      body.style.paddingRight = previousPadding;
    };
  }, []);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message);
      setCopied("done");
    } catch {
      setCopied("failed");
    }
    window.setTimeout(() => setCopied("idle"), 2400);
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 bg-black/75 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Message for payroll"
      onClick={onClose}
    >
      <div
        // Stops a click inside the panel reaching the backdrop's onClose.
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-3xl max-h-[90vh] flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-3 shrink-0">
          <div>
            <h2 className="text-[var(--ink)] text-base font-bold">
              Message for payroll
            </h2>
            <p className="text-[var(--sage)] text-xs mt-1">
              Read it over, then copy. Nothing is sent for you.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 w-8 h-8 rounded-full border border-[var(--border)] bg-[var(--surface-2)] text-[var(--sage)] hover:text-[var(--ink)] text-lg leading-none cursor-pointer transition-colors"
          >
            ×
          </button>
        </div>

        {/* whitespace-pre-wrap, and `message` as a single child, so the
            blank lines between paragraphs render exactly as they copy.

            max-w-3xl on the panel is sized for the shortest viewport this
            has to work on: at 1280x720, max-h-[90vh] leaves 648px, and the
            longest message this produces needs about 530px of that. A
            narrower panel wraps the same text into more lines and eats the
            margin. overflow-y-auto is a safety net for a message longer
            than anything the findings layer currently generates; it does
            not engage at these lengths. */}
        <div className="px-6 pb-5 overflow-y-auto custom-scrollbar">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-5 py-4">
            <div className="whitespace-pre-wrap text-[var(--ink)] text-[15px] sm:text-base leading-relaxed">
              {message}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 pb-5 pt-1 shrink-0">
          {copied === "done" && (
            <span
              role="status"
              className="text-[var(--mint)] text-xs font-medium"
            >
              Copied to clipboard
            </span>
          )}
          {copied === "failed" && (
            <span role="status" className="text-[var(--warn)] text-xs font-medium">
              Couldn&rsquo;t copy &mdash; select the text above instead
            </span>
          )}
          <button
            type="button"
            onClick={copy}
            className="px-5 py-2.5 rounded-xl bg-[var(--amber)] text-black text-xs font-bold uppercase tracking-wider cursor-pointer hover:opacity-90 active:scale-[0.99] transition-all"
          >
            {copied === "done" ? "Copied" : "Copy message"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Portalled to document.body.
 *
 * PrototypeScaffold takes a single render-prop child, so this cannot be a
 * sibling of the screen inside it - and rendering it as a descendant of
 * the phone frame would put a fixed-position element inside a
 * max-w-sm, overflow-hidden box whose ancestors are free to grow a
 * transform later and start acting as its containing block. A portal
 * sidesteps both: the panel is a child of <body> no matter where it is
 * written.
 *
 * No mounted-state effect guard is needed - this only ever renders after
 * a click, so it never runs during SSR.
 */
export function PayrollPreview(props: { message: string; onClose: () => void }) {
  if (typeof document === "undefined") return null;
  return createPortal(<PayrollPreviewPanel {...props} />, document.body);
}
