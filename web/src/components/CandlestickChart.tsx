"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import type { Time, CandlestickData, LineData } from "lightweight-charts";

type PricePoint = { date: string; open: number; high: number; low: number; close: number; volume: number | null };
type IndicatorData = { date: string; rsi: number | null; macd_line: number | null; macd_signal: number | null; macd_hist: number | null; sma_20: number | null; sma_50: number | null; sma_200: number | null; bb_upper: number | null; bb_lower: number | null; bb_mid: number | null; volume_sma_20: number | null; atr: number | null };

function toTime(dateStr: string): Time {
  return Math.floor(Date.parse(dateStr.slice(0, 10)) / 1000) as Time;
}

export function CandlestickChart({ ticker }: { ticker: string }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const indicatorRef = useRef<HTMLDivElement>(null);
  const [period, setPeriod] = useState("1М");
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [indicators, setIndicators] = useState<IndicatorData[]>([]);

  useEffect(() => {
    const daysMap: Record<string, number> = { "1Н": 7, "1М": 30, "3М": 90, "1Г": 365 };
    const days = daysMap[period] || 30;
    Promise.all([
      api.instruments.prices(ticker, days),
      api.instruments.indicators(ticker, days).catch(() => [] as IndicatorData[]),
    ]).then(([p, i]) => {
      setPrices(p);
      setIndicators(i);
    });
  }, [ticker, period]);

  useEffect(() => {
    if (!chartRef.current || prices.length === 0) return;
    let cleanup: (() => void) | undefined;

    import("lightweight-charts").then((lc) => {
      if (!chartRef.current) return;

      const chart = lc.createChart(chartRef.current, {
        width: chartRef.current.clientWidth,
        height: 320,
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

      const candlestickSeries = chart.addSeries(lc.CandlestickSeries, {
        upColor: "#10B981",
        downColor: "#EF4444",
        borderDownColor: "#EF4444",
        borderUpColor: "#10B981",
        wickDownColor: "#EF4444",
        wickUpColor: "#10B981",
      });

      const candleData: CandlestickData[] = prices.map((p) => ({
        time: toTime(p.date),
        open: p.open,
        high: p.high,
        low: p.low,
        close: p.close,
      }));
      candlestickSeries.setData(candleData);

      if (indicators.length > 0) {
        const sma20Data: LineData[] = indicators
          .filter((i): i is IndicatorData & { sma_20: number } => i.sma_20 !== null)
          .map((i) => ({ time: toTime(i.date), value: i.sma_20 as number }));
        if (sma20Data.length > 0) {
          chart.addSeries(lc.LineSeries, { color: "#8B5CF6", lineWidth: 1, lineStyle: lc.LineStyle.Dotted }).setData(sma20Data);
        }

        const sma50Data: LineData[] = indicators
          .filter((i): i is IndicatorData & { sma_50: number } => i.sma_50 !== null)
          .map((i) => ({ time: toTime(i.date), value: i.sma_50 }));
        if (sma50Data.length > 0) {
          chart.addSeries(lc.LineSeries, { color: "#F59E0B", lineWidth: 1, lineStyle: lc.LineStyle.Dotted }).setData(sma50Data);
        }
      }

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
  }, [prices, indicators]);

  useEffect(() => {
    if (!indicatorRef.current || indicators.length === 0) return;
    let cleanup: (() => void) | undefined;

    import("lightweight-charts").then((lc) => {
      if (!indicatorRef.current) return;

      const chart = lc.createChart(indicatorRef.current, {
        width: indicatorRef.current.clientWidth,
        height: 80,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "#9CA3AF",
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.03)" },
          horzLines: { color: "rgba(255,255,255,0.03)" },
        },
        timeScale: { borderColor: "rgba(255,255,255,0.08)", visible: false },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      });

      const rsiData: LineData[] = indicators
        .filter((i): i is IndicatorData & { rsi: number } => i.rsi !== null)
        .map((i) => ({ time: toTime(i.date), value: i.rsi }));
      if (rsiData.length > 0) {
        chart.addSeries(lc.LineSeries, { color: "#8B5CF6", lineWidth: 1 }).setData(rsiData);

        const line70: LineData[] = rsiData.map((d) => ({ time: d.time, value: 70 }));
        const line30: LineData[] = rsiData.map((d) => ({ time: d.time, value: 30 }));
        chart.addSeries(lc.LineSeries, { color: "#EF4444", lineWidth: 1, lineStyle: lc.LineStyle.Dashed }).setData(line70);
        chart.addSeries(lc.LineSeries, { color: "#10B981", lineWidth: 1, lineStyle: lc.LineStyle.Dashed }).setData(line30);
      }

      cleanup = () => chart.remove();
    });

    return () => cleanup?.();
  }, [indicators]);

  const periods = ["1Н", "1М", "3М", "1Г"];

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-light text-white">График</h2>
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
      {indicators.some((i) => i.rsi !== null) && (
        <div className="mt-2">
          <p className="text-[10px] text-gray-600 mb-1">RSI (14)</p>
          <div ref={indicatorRef} className="w-full" />
        </div>
      )}
    </section>
  );
}
