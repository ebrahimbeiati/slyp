export interface MockQA {
  id: string;
  label: string;
  question: string;
  answer: string;
}

export const MOCK_QA_DATA: MockQA[] = [
  {
    id: "q1",
    label: "🤔 Why is my tax code 1257L?",
    question: "Why is my current tax code 1257L?",
    answer: "This is the standard tax code for most UK employees. It means you have a Personal Allowance of £12,570, which is the amount of income you can earn completely tax-free this year.",
  },
  {
    id: "q2",
    label: "📊 How is my net pay calculated?",
    question: "How do you calculate my net take-home pay?",
    answer: "We start with your Gross Salary, then subtract your Income Tax, Employee National Insurance (NI) contributions, and any voluntary workplace pension deductions.",
  },
  {
    id: "q3",
    label: "🚨 Will I trigger the next tax bracket?",
    question: "Am I close to triggering the next tax bracket?",
    answer: "Based on your current baseline trends, you are securely within the basic rate bracket. The Higher Rate (40%) band applies only to earnings over £50,270.",
  },
  {
    id: "q4",
    label: "🛡️ Is my student loan repayment correct?",
    question: "How are my student loan deductions calculated?",
    answer: "Deductions depend on your plan type. For Plan 2, you pay 9% on everything earned over the £27,295 annual threshold (£2,274 a month). This is calculated automatically per pay period.",
  },
  {
    id: "q5",
    label: "📈 What does 'Emergency Tax' code mean?",
    question: "Why do I see an emergency tax indicator?",
    answer: "If your code shows BR, 0T, or ends in W1/M1, you are being taxed on all income without a personal allowance. This usually happens when starting a new job before HMRC updates your record.",
  },
  {
    id: "q6",
    label: "💰 Why did my National Insurance change?",
    question: "Why is my National Insurance different this month?",
    answer: "National Insurance is calculated based on exact earnings within each specific pay period rather than cumulatively. Spikes in overtime or bonuses trigger higher NI percentages instantly.",
  },
  {
    id: "q7",
    label: "🛑 How do pension deductions save me tax?",
    question: "Are my pension contributions tax-free?",
    answer: "Yes, under a 'Net Pay Arrangement', your pension contribution is taken out of your gross salary before income tax is calculated. This immediately lowers your total taxable income.",
  },
  {
    id: "q8",
    label: "💼 What if I have a second job?",
    question: "How does having a second job affect my taxes?",
    answer: "HMRC usually splits your Personal Allowance or applies a 'BR' (Basic Rate) code to your second job, meaning that entire secondary paycheck is taxed at a flat 20% from the very first pound.",
  },
  {
    id: "q9",
    label: "⏳ What happens to my tax if I do overtime?",
    question: "Does overtime put me in a higher tax bracket permanently?",
    answer: "No. While a large overtime paycheck might cause a temporary higher tax deduction that specific month, HMRC calculates your absolute bracket cumulatively. Any overpayment aligns by year-end.",
  },
  {
    id: "q10",
    label: "📝 How do I claim back overpaid tax?",
    question: "Can I request a tax refund through this app?",
    answer: "If you overpaid due to a temporary emergency tax code, HMRC automatically adjusts your code on your next paycheck to refund you, or issues a P800 refund check after the tax year ends.",
  },
];
