"use client";

import { useState } from "react";
import type { ChartRange } from "@/types/chart";
import PriceChart from "@/components/bonds/details/PriceChartCard/PriceChart";
import ChartToolbar from "@/components/bonds/details/PriceChartCard/ChartToolbar";
import { formatCurrency, formatPercent } from "@/lib/format";

interface Props {
  data: { time: string; value: number }[];
  totalReturn: number;
  currentValue: number;
}

export default function PortfolioPerformance({ data, totalReturn, currentValue }: Props) {
  const [range, setRange] = useState<ChartRange>("1M");
  const positive = totalReturn >= 0;

  const filtered = (() => {
    const now = Date.now();
    const ranges: Record<string, number> = {
      "1D": 86_400_000,
      "5D": 5 * 86_400_000,
      "1M": 30 * 86_400_000,
      "3M": 90 * 86_400_000,
      "6M": 180 * 86_400_000,
      "1Y": 365 * 86_400_000,
      "3Y": 3 * 365 * 86_400_000,
      ALL: Infinity,
    };
    const cutoff = now - (ranges[range] ?? ranges["1M"]);
    return data.filter((p) => new Date(p.time).getTime() >= cutoff);
  })();

  return (
    <div className="rounded-xl border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Стоимость портфеля
        </h3>
        <ChartToolbar selected={range} onChange={setRange} />
      </div>

      <div className="mb-4 flex items-baseline gap-3">
        <span className="text-2xl font-bold tabular-nums text-foreground">
          {formatCurrency(currentValue)}
        </span>
        <span className={`text-lg font-semibold tabular-nums ${positive ? "text-emerald-500" : "text-red-500"}`}>
          {positive ? "+" : ""}{formatPercent(totalReturn)}
        </span>
      </div>

      <PriceChart priceData={filtered} volumeData={[]} height={240} />
    </div>
  );
}
