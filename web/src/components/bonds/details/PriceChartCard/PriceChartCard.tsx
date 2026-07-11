"use client";

import { useState, useMemo } from "react";
import type { ChartRange, ChartData } from "@/types/chart";
import PriceChart from "./PriceChart";
import ChartToolbar from "./ChartToolbar";
import ChartLegend, { type LegendItem } from "./ChartLegend";
import ChartStats from "./ChartStats";

interface Props {
  data: ChartData;
  currentPrice: number;
  volume: number;
}

function generateStats(data: ChartData, currentPrice: number, volume: number) {
  const values = data.price.map((p) => p.value);
  const first = values[0] ?? currentPrice;
  const change = first !== 0 ? ((currentPrice - first) / first) * 100 : 0;
  const high = Math.max(...values, currentPrice);
  const low = Math.min(...values, currentPrice);

  return { currentPrice, change, high, low, volume };
}

export default function PriceChartCard({ data, currentPrice, volume }: Props) {
  const [range, setRange] = useState<ChartRange>("1M");
  const [showMA20, setShowMA20] = useState(false);
  const [showMA50, setShowMA50] = useState(false);
  const [showFairValue, setShowFairValue] = useState(false);

  const filtered = useMemo(() => {
    const now = Date.now();
    const ranges: Record<ChartRange, number> = {
      "1D": 86_400_000,
      "5D": 5 * 86_400_000,
      "1M": 30 * 86_400_000,
      "3M": 90 * 86_400_000,
      "6M": 180 * 86_400_000,
      "1Y": 365 * 86_400_000,
      "3Y": 3 * 365 * 86_400_000,
      "ALL": Infinity,
    };
    const cutoff = now - ranges[range];
    return {
      price: data.price.filter((p) => new Date(p.time).getTime() >= cutoff),
      volume: data.volume.filter((v) => new Date(v.time).getTime() >= cutoff),
    };
  }, [data, range]);

  const stats = generateStats(filtered, currentPrice, volume);

  const legendItems: LegendItem[] = [
    { id: "price", label: "Цена", color: "#22c55e", active: true, onToggle: () => {} },
    { id: "ma20", label: "MA20", color: "#3b82f6", active: showMA20, onToggle: () => setShowMA20((v) => !v) },
    { id: "ma50", label: "MA50", color: "#f59e0b", active: showMA50, onToggle: () => setShowMA50((v) => !v) },
    { id: "fairValue", label: "AI Fair Value", color: "#a855f7", active: showFairValue, onToggle: () => setShowFairValue((v) => !v) },
  ];

  return (
    <div className="rounded-xl border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Цена
        </h3>
        <ChartToolbar selected={range} onChange={setRange} />
      </div>

      <div className="mb-3">
        <ChartLegend items={legendItems} />
      </div>

      <PriceChart priceData={filtered.price} volumeData={filtered.volume} />

      <div className="mt-4 border-t border-border/50 pt-4">
        <ChartStats stats={stats} />
      </div>
    </div>
  );
}
