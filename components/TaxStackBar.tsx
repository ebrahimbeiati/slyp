import type { UserFinancials } from "@/app/Types/Types";

export function TaxStackBar({ financials }: { readonly financials: UserFinancials }) {
  const total = financials.combinedGrossThisMonth;
  if (total <= 0) return null;

  const taxPct = (financials.currentMonthPayslips.reduce((sum, p) => sum + p.incomeTax, 0) / total) * 100;
  const niPct = (financials.currentMonthPayslips.reduce((sum, p) => sum + p.nationalInsurance, 0) / total) * 100;
  const pensionPct = (financials.currentMonthPayslips.reduce((sum, p) => sum + p.pensionContribution, 0) / total) * 100;
  const netPct = 100 - taxPct - niPct - pensionPct;

  return (
    <div className="space-y-4">
      <div className="h-4 rounded-lg overflow-hidden flex border" style={{ borderColor: "rgba(243, 246, 242, 0.08)" }}>
        {taxPct > 0 && <div className="flex-shrink-0" style={{ width: `${taxPct}%`, backgroundColor: "var(--warn)" }} />}
        {niPct > 0 && <div className="flex-shrink-0" style={{ width: `${niPct}%`, backgroundColor: "#5B7A70" }} />}
        {pensionPct > 0 && <div className="flex-shrink-0" style={{ width: `${pensionPct}%`, backgroundColor: "var(--sage)" }} />}
        {netPct > 0 && <div className="flex-shrink-0" style={{ width: `${netPct}%`, backgroundColor: "var(--mint)" }} />}
      </div>

      <div className="flex flex-wrap gap-4 text-xs">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "var(--warn)" }} />
          <span style={{ color: "var(--sage)" }}>Tax</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "#5B7A70" }} />
          <span style={{ color: "var(--sage)" }}>NI</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "var(--sage)" }} />
          <span style={{ color: "var(--sage)" }}>Pension</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "var(--mint)" }} />
          <span style={{ color: "var(--sage)" }}>Net</span>
        </div>
      </div>
    </div>
  );
}
