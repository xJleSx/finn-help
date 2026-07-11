import type { BondAnalysis } from "@/types/bond-analysis";
import AIScoreHeader from "./AIScoreHeader";
import VerdictBadge from "./VerdictBadge";
import ProsList from "./ProsList";
import RisksList from "./RisksList";
import PortfolioAllocation from "./PortfolioAllocation";

interface Props {
  name: string;
  ticker: string;
  analysis: BondAnalysis;
}

export default function AISummaryCard({ name, ticker, analysis }: Props) {
  return (
    <div className="space-y-5 rounded-xl border bg-card p-6">
      <AIScoreHeader name={name} ticker={ticker} score={analysis.score} />
      <VerdictBadge verdict={analysis.verdict} />
      <div className="h-px bg-border/50" />
      <ProsList items={analysis.pros} />
      {analysis.risks.length > 0 && <div className="h-px bg-border/50" />}
      <RisksList risks={analysis.risks} />
      <div className="h-px bg-border/50" />
      <PortfolioAllocation allocation={analysis.allocation} />
      <div className="text-xs text-muted-foreground">
        Последнее обновление AI: {new Date(analysis.updatedAt).toLocaleString("ru-RU")}
      </div>
    </div>
  );
}
