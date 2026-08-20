import type { UserFinancials } from "../app/Types/Types";

type AnswerEntry = {
  keywords: string[];
  answer: string | ((ctx: UserFinancials) => string);
};

const ANSWERS: AnswerEntry[] = [
  {
    keywords: ["tax code", "1257l", "what does my tax code mean"],
    answer: (ctx) => {
      const code = ctx.currentMonthPayslips[0]?.taxCode ?? "your tax code";
      return `${code} tells your employer how much you can earn before tax. 1257L is the standard code for most people with one job and the full Personal Allowance (£12,570/year). Letters like BR mean "basic rate on everything" — usually used for a second job.`;
    },
  },
  {
    keywords: ["national insurance", "ni", "what is ni"],
    answer:
      "National Insurance funds things like the State Pension and NHS. You pay it once you earn over a threshold, separately from Income Tax — that's why your payslip shows two different deduction lines.",
  },
  {
    keywords: ["pension", "workplace pension", "auto enrolment", "auto-enrolment"],
    answer:
      "Most jobs automatically enrol you into a workplace pension once you're over 22 and earning above £10,000/year. A slice of your pay goes in before tax, and your employer usually adds their own contribution on top — it's essentially free money toward retirement.",
  },
  {
    keywords: ["bracket", "higher rate", "40%", "next bracket"],
    answer: (ctx) => {
      if (ctx.distanceToNextBracket == null) {
        return "You're not close to crossing into a higher tax bracket right now based on your current projected earnings.";
      }
      return `You're about £${Math.round(ctx.distanceToNextBracket)} away from the next tax bracket this year based on your current pace. Only income above that line gets taxed at the higher rate — the rest stays taxed as it is now.`;
    },
  },
  {
    keywords: ["second job", "two jobs", "multiple jobs", "br code"],
    answer:
      "If you've got more than one job, your second job's tax code is usually BR (basic rate on all of it) or D0, because your main job already uses your tax-free allowance. If a second job isn't on one of those, it's worth checking with HMRC — you might be paying more or less tax than expected.",
  },
  {
    keywords: ["net pay", "take home", "why is my pay lower"],
    answer:
      "Net pay is what actually lands in your account — gross pay minus Income Tax, National Insurance, and pension contributions (if you're enrolled). Those three are almost always the gap between the number on your contract and the number in your bank.",
  },
  {
    keywords: ["extra hours", "more hours", "overtime"],
    answer:
      "Use the part-time calculator on your dashboard — it estimates how many extra hours you can work this month before you start paying tax on the additional earnings, based on your current hourly rate.",
  },
];

const FALLBACK_ANSWER =
  "I don't have a specific answer for that yet — try asking about your tax code, National Insurance, pension, or how close you are to the next tax bracket.";

/**
 * Keyword match against the user's question. `context` is accepted now (and
 * used by a couple of entries above) so the function signature doesn't need
 * to change when this becomes a real LLM call.
 */
export function findAnswer(question: string, context: UserFinancials): string {
  const q = question.toLowerCase();
  const match = ANSWERS.find((entry) => entry.keywords.some((k) => q.includes(k)));
  if (!match) return FALLBACK_ANSWER;
  return typeof match.answer === "function" ? match.answer(context) : match.answer;
}