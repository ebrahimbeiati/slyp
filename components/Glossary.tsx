"use client";

import { AccordionCard } from "@/components/AccordionCard";

/**
 * The three things people are most embarrassed to ask about, on the empty
 * state so there is something worth reading before the first upload.
 *
 * Kept SHORT on purpose. Someone opening one of these has just admitted
 * they do not know what a tax code is; three paragraphs of prose is the
 * wrong reward for that. Each card is a one-line answer, a scannable
 * table, and at most one follow-up line. If a card needs more than that,
 * it belongs somewhere other than a payslip checker.
 *
 * STATIC PROSE ONLY. Nothing here is computed, and nothing here is
 * derived from the user's payslip - every figure is a published national
 * threshold, written out as text. That is deliberate: the rule this
 * product is built on is that code calculates and the model explains, and
 * the corollary for the frontend is that it does not calculate at all.
 * The design prototype this came from shipped a live "tax-free hours"
 * calculator that divided a hardcoded Personal Allowance by twelve in the
 * browser; that is exactly what is not being copied across. Written out
 * in words rather than as the expression, so that grepping the built
 * bundle for tax constants stays a clean check.
 *
 * Figures checked against slyp/calculations.py, not against the
 * prototype: PERSONAL_ALLOWANCE 12570, NI_WEEKLY_PRIMARY_THRESHOLD 242,
 * NI_WEEKLY_UPPER_EARNINGS_LIMIT 967, NI category A rates 0.08 / 0.02,
 * TAX_YEAR 2026/27. If the engine's constants move for a new tax year,
 * this copy moves with them.
 */

function Row({ term, detail }: { term: string; detail: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 border-b border-[var(--border)] last:border-b-0">
      <div className="text-[var(--ink)] text-[11px] font-bold shrink-0">{term}</div>
      <div className="text-[var(--sage)] text-[10px] leading-snug text-right">
        {detail}
      </div>
    </div>
  );
}

function Card({
  title,
  subtitle,
  lead,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  lead: string;
  children: React.ReactNode;
  footer?: string;
}) {
  return (
    <AccordionCard
      header={
        <>
          <h3 className="text-[var(--ink)] text-xs font-bold leading-tight">
            {title}
          </h3>
          <p className="text-[var(--sage)] text-[10px] mt-0.5">{subtitle}</p>
        </>
      }
    >
      <p className="text-[var(--sage)] text-[10px] leading-relaxed mb-1">
        {lead}
      </p>
      {children}
      {footer && (
        <p className="text-[var(--sage)] text-[10px] leading-relaxed mt-2">
          {footer}
        </p>
      )}
    </AccordionCard>
  );
}

export function Glossary() {
  return (
    <div className="w-full text-left">
      <div className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium mb-2">
        Worth knowing
      </div>

      <Card
        title="Tax code"
        subtitle="What the letters and numbers mean"
        lead="Tells your employer how much you can be paid before tax. It's on every payslip."
        footer="A code left over from an old job is a common reason people overpay without noticing."
      >
        <Row term="1257" detail="× 10 = £12,570 tax-free a year" />
        <Row term="L" detail="Standard allowance. Most common." />
        <Row term="BR" detail="Flat 20%, no allowance. Normal on a second job." />
        <Row term="D0" detail="Flat 40%, no allowance." />
        <Row term="W1 / M1 / X" detail="Emergency. Each payslip taxed on its own." />
        <Row term="K" detail="You owe extra, so it's added to your pay before tax." />
      </Card>

      <Card
        title="National Insurance"
        subtitle="What it funds, and how it counts"
        lead="A separate deduction from income tax. It pays towards the State Pension."
        footer="It builds up as qualifying years, not money back — about 35 for the full State Pension."
      >
        <Row term="8%" detail="On £242–£967 a week (category A)" />
        <Row term="2%" detail="On anything above £967 a week" />
      </Card>

      <Card
        title="Pension"
        subtitle="Where the deduction goes"
        lead="Pay put into a pot you can't draw on until later. Usually invested, so it can rise or fall."
      >
        <Row term="3%+" detail="From your employer" />
        <Row term="The rest" detail="From you, part of it as tax relief" />
        <Row term="8%" detail="Minimum going in, under auto-enrolment" />
      </Card>

      <p className="text-[var(--sage)] text-[9px] leading-relaxed opacity-70 mt-1">
        General info for 2026/27, not financial advice. Check GOV.UK for your
        own situation.
      </p>
    </div>
  );
}
