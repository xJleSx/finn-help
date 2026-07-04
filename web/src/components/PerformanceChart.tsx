"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import type { LineData } from "lightweight-charts";

type Position = {
  id: number;
  ticker: string;
  quantity: number;
  avg_price: number | null;
  current_price: number | null;
  value: number;
  profit_pct: number | null;
};

export function PerformanceChart({ positions }: { positions: Position[] }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [period, setPeriod] = useState("1М");
  const [chartData, setChartData] = useState<{ time: number; value: number }[]>([]);

  useEffect(() => {
    if (positions.length === 0) return;
    let cancelled = false;

    const daysMap: Record<string, number> = { "1Н": 7, "1М": 30, "3М": 90, "1Г": 365 };
    const days = daysMap[period] || 30;

    Promise.all(
      positions.map(async (p) => {
        try {
          const data = await api.instruments.prices(p.ticker, days);
          return { ticker: p.ticker, data, quantity: p.quantity };
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      const valid = results.filter((r): r is NonNullable<typeof r> => r !== null && r.data.length > 1);
      if (valid.length === 0) { return; }

      const dateSet = new Set<string>();
      for (const r of valid) {
        for (const p of r.data) {
          if (p.close > 0) dateSet.add(p.date.slice(0, 10));
        }
      }
      const dates = Array.from(dateSet).sort();

      const totalCost = positions.reduce((s, p) => s + (p.avg_price ?? p.current_price ?? 0) * p.quantity, 0);
      if (totalCost <= 0) { return; }

      const perfData = dates.map((date) => {
        let totalValue = 0;
        for (const r of valid) {
          const pricePoint = r.data.find((p) => p.date.slice(0, 10) === date);
          if (pricePoint && pricePoint.close > 0) {
            totalValue += pricePoint.close * r.quantity;
          }
        }
        const pct = totalCost > 0 ? ((totalValue - totalCost) / totalCost) * 100 : 0;
        const ms = Date.parse(date);
        return { time: Math.floor(ms / 1000), value: parseFloat(pct.toFixed(2)) };
      });

      setChartData(perfData);
    });

    return () => { cancelled = true; };
  }, [positions, period]);

  useEffect(() => {
    if (!chartRef.current || chartData.length === 0) return;

    let cleanup: (() => void) | undefined;

    import("lightweight-charts").then((lc) => {
      if (!chartRef.current) return;

      const chart = lc.createChart(chartRef.current, {
        width: chartRef.current.clientWidth,
        height: 220,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "#9CA3AF",
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.03)" },
          horzLines: { color: "rgba(255,255,255,0.03)" },
        },
        crosshair: {
          vertLine: { color: "#F0B90B", width: 1, style: lc.LineStyle.Dashed },
          horzLine: { color: "#F0B90B", width: 1, style: lc.LineStyle.Dashed },
        },
        timeScale: { borderColor: "rgba(255,255,255,0.08)" },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      });

      const color = chartData[chartData.length - 1]?.value >= chartData[0]?.value ? "#10B981" : "#EF4444";
      const line = chart.addSeries(lc.LineSeries, {
        color,
        lineWidth: 2,
        crosshairMarkerVisible: true,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });
      line.setData(chartData as LineData[]);

      const handleResize = () => {
        if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
      };
      window.addEventListener("resize", handleResize);

      cleanup = () => {
        window.removeEventListener("resize", handleResize);
        chart.remove();
      };
    });

    return () => cleanup?.();
  }, [chartData]);

  if (positions.length === 0) return null;

  const periods = ["1Н", "1М", "3М", "1Г"];

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-light text-white">Доходность портфеля</h2>
        <div className="flex bg-white/5 rounded-lg p-0.5">
          {periods.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2.5 py-1 text-xs rounded-md transition ${period === p ? "bg-amber-400/20 text-amber-400" : "text-gray-500 hover:text-white"}`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <div ref={chartRef} className="w-full" />
      {chartData.length === 0 && (
        <div className="h-[220px] flex items-center justify-center">
          <p className="text-xs text-gray-600">Нет данных для графика</p>
        </div>
      )}
    </section>
  );
}
