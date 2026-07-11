import type { CashFlowItemData, CashFlowSummaryData } from "@/types/cash-flow";
import CashFlowTimeline from "./CashFlowTimeline";
import CashFlowSummary from "./CashFlowSummary";

interface Props {
  items: CashFlowItemData[];
  summary: CashFlowSummaryData;
}

export default function CashFlowCard({ items, summary }: Props) {
  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Cash Flow
      </h3>
      <CashFlowTimeline items={items} />
      <CashFlowSummary summary={summary} />
    </div>
  );
}
