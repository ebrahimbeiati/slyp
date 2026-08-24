"use client";

import { AccordionCard } from "@/components/AccordionCard";

/**
 * The three things people are most embarrassed to ask about, on the empty
 * state so there is something worth reading before the first upload.
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
 * HIGHER_RATE_THRESHOLD 50270, ADDITIONAL_RATE_THRESHOLD 125140, TAX_YEAR
 * 2026/27. If the engine's constants move for a new tax year, this copy
 * moves with them.
 */

function Row({ term, detail }: { term: string; detail: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2 border-b border-[var(--border)] last:border-b-0">
      <div className="text-[var(--ink)] text-[11px] font-bold shrink-0">{term}</div>
      <div className="text-[var(--sage)] text-[10px] leading-relaxed text-right">
        {detail}
      </div>
    </div>
  );
}

function Body({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[var(--sage)] text-[10px] leading-relaxed space-y-2">
      {children}
    </div>
  );
}

export function Glossary() {
  return (
    <div className="w-full text-left">
      <div className="text-[10px] uppercase tracking-wider text-[var(--sage)] font-medium mb-2">
        Worth knowing
      </div>
      <p className="text-[var(--sage)] text-[11px] leading-relaxed mb-3">
        The three things people are most embarrassed to ask about, explained
        properly.
      </p>

      <AccordionCard
        header={
          <>
            <h3 className="text-[var(--ink)] text-xs font-bold leading-tight">
              Tax code
            </h3>
            <p className="text-[var(--sage)] text-[10px] mt-0.5">
              What the letters and numbers mean
            </p>
          </>
        }
      >
        <Body>
          <p>
            Your tax code tells your employer how much you can be paid before
            tax is taken. It is printed on every payslip &mdash; most often{" "}
            <strong className="text-[var(--ink)]">1257L</strong>.
          </p>
          <div className="py-1">
            <Row term="1257" detail="× 10 = £12,570 tax-free for the year" />
            <Row term="L" detail="The standard allowance. Most common." />
            <Row
              term="BR"
              detail="Flat 20%, no allowance here. Normal on a second job."
            />
            <Row term="D0" detail="Flat 40%, no allowance." />
            <Row
              term="W1 / M1 / X"
              detail="Emergency basis. Each payslip taxed on its own, ignoring the year so far."
            />
            <Row
              term="K"
              detail="You owe extra tax, so an amount is added to your pay before tax rather than taken off."
            />
          </div>
          <p>
            A code that is wrong &mdash; say, still on BR from a job you have
            left &mdash; is one of the most common reasons people over- or
            underpay without noticing.
          </p>
        </Body>
      </AccordionCard>

      <AccordionCard
        header={
          <>
            <h3 className="text-[var(--ink)] text-xs font-bold leading-tight">
              National Insurance
            </h3>
            <p className="text-[var(--sage)] text-[10px] mt-0.5">
              What it funds, and how it counts
            </p>
          </>
        }
      >
        <Body>
          <p>
            National Insurance is a separate deduction from income tax. It pays
            towards the State Pension and other contributory benefits.
          </p>
          <div className="py-1">
            <Row
              term="8%"
              detail="On earnings between £242 and £967 a week, on the most common category (A)"
            />
            <Row term="2%" detail="On anything above £967 a week" />
          </div>
          <p>
            It builds up as{" "}
            <strong className="text-[var(--ink)]">qualifying years</strong>, not
            as money returned to you. Each tax year you earn above a threshold
            counts as one, and roughly 35 are needed for the full new State
            Pension.
          </p>
          <p>
            Gaps &mdash; time out of work, or working abroad &mdash; can leave
            holes in that record. You can check yours on GOV.UK.
          </p>
        </Body>
      </AccordionCard>

      <AccordionCard
        header={
          <>
            <h3 className="text-[var(--ink)] text-xs font-bold leading-tight">
              Pension
            </h3>
            <p className="text-[var(--sage)] text-[10px] mt-0.5">
              Where the deduction goes
            </p>
          </>
        }
      >
        <Body>
          <p>
            A slice of your pay goes into a pot you cannot draw on until later
            in life. It is usually invested rather than held as cash.
          </p>
          <p>
            Under automatic enrolment the minimum going in is 8% of your
            qualifying earnings: at least 3% from your employer and the rest
            from you, with part of your share arriving as tax relief instead of
            tax you would have paid. Your own scheme may put in more than the
            minimum.
          </p>
          <p>
            Two things add to it over time: new contributions every payslip,
            and any growth on what is already invested &mdash; which can fall as
            well as rise.
          </p>
        </Body>
      </AccordionCard>

      <p className="text-[var(--sage)] text-[9px] leading-relaxed opacity-70 mt-1">
        General information for the 2026/27 tax year, not financial advice. For
        your own circumstances, check GOV.UK or speak to HMRC.
      </p>
    </div>
  );
}
