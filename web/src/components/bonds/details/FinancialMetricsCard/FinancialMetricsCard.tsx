import { TrendingUp, DollarSign, Clock, ChevronDown, Landmark, Receipt, ArrowRight, BarChart3, TrendingDown, Sparkles } from "lucide-react";
import type { BondMetrics } from "@/types/bond-metrics";
import { formatPercent, formatCurrency } from "@/lib/format";
import MetricGrid from "./MetricGrid";
import MetricCard from "./MetricCard";

interface Props {
  metrics: BondMetrics;
}

export default function FinancialMetricsCard({ metrics }: Props) {
  const profitPositive = metrics.profit >= 0;
  const profitPct = metrics.purchasePrice > 0 ? (metrics.profit / metrics.purchasePrice) * 100 : 0;

  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-6 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Финансовые показатели
      </h3>
      <MetricGrid>
        <MetricCard
          title="Доходность к погашению"
          value={formatPercent(metrics.yieldToMaturity)}
          trend="positive"
          subtitle="YTM"
          icon={<TrendingUp className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="Текущая доходность"
          value={formatPercent(metrics.currentYield)}
          trend="positive"
          subtitle="Current Yield"
          icon={<PercentIcon />}
        />
        <MetricCard
          title="Дюрация"
          value={metrics.duration.toFixed(2)}
          trend="neutral"
          subtitle="Macaulay"
          icon={<Clock className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="Модифицированная дюрация"
          value={metrics.modifiedDuration.toFixed(2)}
          trend="neutral"
          subtitle="Modified"
          icon={<ChevronDown className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="Купон"
          value={formatCurrency(metrics.coupon)}
          subtitle="на одну облигацию"
          icon={<Landmark className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="НКД"
          value={formatCurrency(metrics.accruedInterest)}
          subtitle="накопленный доход"
          icon={<Receipt className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="Цена покупки"
          value={formatCurrency(metrics.purchasePrice)}
          icon={<ArrowRight className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="Текущая цена"
          value={formatCurrency(metrics.marketPrice)}
          icon={<BarChart3 className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="Прибыль"
          value={`${profitPositive ? "+" : ""}${formatPercent(profitPct)}`}
          subtitle={formatCurrency(metrics.profit)}
          trend={profitPositive ? "positive" : "negative"}
          icon={profitPositive ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
        />
        <MetricCard
          title="AI Справедливая цена"
          value={formatCurrency(metrics.fairValue)}
          trend={metrics.fairValue > metrics.marketPrice ? "positive" : "negative"}
          subtitle={metrics.fairValue > metrics.marketPrice ? "недооценено" : "переоценено"}
          icon={<Sparkles className="h-3.5 w-3.5" />}
        />
      </MetricGrid>
    </div>
  );
}

function PercentIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="5" x2="5" y2="19" />
      <circle cx="6.5" cy="6.5" r="2.5" />
      <circle cx="17.5" cy="17.5" r="2.5" />
    </svg>
  );
}
