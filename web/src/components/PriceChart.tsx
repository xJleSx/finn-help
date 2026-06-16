"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type PricePoint = { date: string; close: number; volume?: number };

type Instrument = {
  id: number; ticker: string; full_name: string; type: string;
  last_price: number | null; last_date: string | null;
};

export default function PriceChart({ ticker, company }: { ticker: string; company: string }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [period, setPeriod] = useState("1M");
  const [showSMA, setShowSMA] = useState(false);

  useEffect(() => {
    const daysMap: Record<string, number> = { "1Н": 7, "1М": 30, "3М": 90, "1Г": 365 };
    const days = daysMap[period] || 30;
    fetch(`${API}/api/instruments/${ticker}/prices?days=${days}`)
      .then((r) => r.json())
      .then(setPrices)
      .catch(() => setPrices([]));
  }, [ticker, period]);

  useEffect(() => {
    if (!chartRef.current || prices.length === 0) return;
    let chart: any, line: any, smaLine: any;

    import("lightweight-charts").then((lc) => {
      chart = lc.createChart(chartRef.current!, {
        width: chartRef.current!.clientWidth,
        height: 280,
        layout: { background: { type: lc.ColorType.Solid, color: "transparent" } as any, textColor: "#9CA3AF" },
        grid: { vertLines: { color: "rgba(255,255,255,0.03)" }, horzLines: { color: "rgba(255,255,255,0.03)" } },
        crosshair: { vertLine: { color: "#F0B90B", width: 1, style: 2 }, horzLine: { color: "#F0B90B", width: 1, style: 2 } },
        timeScale: { borderColor: "rgba(255,255,255,0.08)" },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      });

      const data = prices.map((p) => ({ time: p.date.slice(0, 10), value: p.close }));
      line = chart.addLineSeries({ color: "#F0B90B", lineWidth: 2, crosshairMarkerVisible: true });
      line.setData(data);

      if (showSMA) {
        const smaData = data.map((d, i, arr) => {
          if (i < 19) return d;
          const vals = arr.slice(i - 19, i + 1).map((x) => x.value);
          return { ...d, value: vals.reduce((a, b) => a + b, 0) / vals.length };
        });
        smaLine = chart.addLineSeries({ color: "#10B981", lineWidth: 1, lineStyle: 2 });
        smaLine.setData(smaData);
      }

      const handleResize = () => {
        if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
      };
      window.addEventListener("resize", handleResize);
      return () => {
        window.removeEventListener("resize", handleResize);
        chart.remove();
      };
    });
  }, [prices, showSMA]);

  const periods = ["1Н", "1М", "3М", "1Г"];

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">{ticker} — {company}</h3>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={showSMA} onChange={(e) => setShowSMA(e.target.checked)} className="accent-amber-400" />
            SMA 20
          </label>
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
      </div>
      <div ref={chartRef} className="w-full" />
    </div>
  );
}
