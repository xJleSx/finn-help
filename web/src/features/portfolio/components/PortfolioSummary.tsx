import StatCard from "@/features/market/components/cards/StatCard";
import { formatCurrency, formatPercent } from "@/lib/format";
import type { BondPortfolioSummary } from "@/features/portfolio/types/bond-summary";

interface Props {
  summary: BondPortfolioSummary;
}

export default function PortfolioSummary({ summary }: Props) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
      <StatCard title="Стоимость" value={formatCurrency(summary.totalValue)} />
      <StatCard
        title="Доход"
        value={`${summary.totalProfit >= 0 ? "+" : ""}${formatCurrency(summary.totalProfit)}`}
      />
      <StatCard
        title="Доходность"
        value={formatPercent(summary.totalReturn)}
        subtitle={`${summary.totalReturn >= 0 ? "+" : ""}${formatPercent(summary.totalReturn)}`}
      />
      <StatCard title="Средний YTM" value={formatPercent(summary.avgYtm)} />
      <StatCard title="Средний AI" value={String(summary.avgAiScore)} />
    </div>
  );
}
