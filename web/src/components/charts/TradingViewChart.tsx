"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  AreaSeries,
  ColorType,
  LineStyle,
} from "lightweight-charts";
import type {
  IChartApi,
  CandlestickData,
  LineData,
  HistogramData,
  DeepPartial,
  TimeChartOptions,
} from "lightweight-charts";

export interface OHLCVData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Props {
  data: OHLCVData[];
  width?: number;
  height?: number;
  overlays?: {
    sma?: boolean;
    bb?: boolean;
    rsi?: boolean;
    volume?: boolean;
  };
  chartType?: "candlestick" | "line" | "area";
}

function computeSMA(data: OHLCVData[], period: number): LineData[] {
  const out: LineData[] = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += data[j].close;
    out.push({ time: data[i].time, value: sum / period });
  }
  return out;
}

function computeBB(data: OHLCVData[], period: number, mult: number) {
  const smaVals = computeSMA(data, period);
  const out: { upper: LineData; middle: LineData; lower: LineData }[] = [];
  for (let i = period - 1; i < data.length; i++) {
    const mean = smaVals[i - period + 1].value;
    let sumSq = 0;
    for (let j = i - period + 1; j <= i; j++) sumSq += (data[j].close - mean) ** 2;
    const std = Math.sqrt(sumSq / period);
    const time = data[i].time;
    out.push({
      upper: { time, value: mean + mult * std },
      middle: { time, value: mean },
      lower: { time, value: mean - mult * std },
    });
  }
  return out;
}

function computeRSI(data: OHLCVData[], period: number): LineData[] {
  const out: LineData[] = [];
  if (data.length < period + 1) return out;
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = data[i].close - data[i - 1].close;
    avgGain += Math.max(diff, 0);
    avgLoss += Math.max(-diff, 0);
  }
  avgGain /= period;
  avgLoss /= period;
  let rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  out.push({ time: data[period].time, value: 100 - 100 / (1 + rs) });
  for (let i = period + 1; i < data.length; i++) {
    const diff = data[i].close - data[i - 1].close;
    const gain = Math.max(diff, 0);
    const loss = Math.max(-diff, 0);
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    out.push({ time: data[i].time, value: 100 - 100 / (1 + rs) });
  }
  return out;
}

const chartTheme: DeepPartial<TimeChartOptions> = {
  layout: {
    background: { type: ColorType.Solid, color: "transparent" },
    textColor: "#a1a1aa",
  },
  grid: {
    vertLines: { color: "#27272a" },
    horzLines: { color: "#27272a" },
  },
  rightPriceScale: { borderColor: "#27272a" },
  timeScale: {
    borderColor: "#27272a",
    timeVisible: true,
    secondsVisible: false,
  },
  crosshair: {
    vertLine: {
      color: "#52525b",
      width: 1 as const,
      style: LineStyle.Dashed,
      labelBackgroundColor: "#18181b",
    },
    horzLine: {
      color: "#52525b",
      width: 1 as const,
      style: LineStyle.Dashed,
      labelBackgroundColor: "#18181b",
    },
  },
  handleScroll: true,
  handleScale: true,
};

export default function TradingViewChart({
  data,
  width,
  height = 400,
  overlays = {},
  chartType = "candlestick",
}: Props) {
  const mainRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);

  const showVolume = overlays.volume !== false;
  const showSma = overlays.sma === true;
  const showBb = overlays.bb === true;
  const showRsi = overlays.rsi === true;

  const mainH = showRsi ? height - 80 : height;

  useEffect(() => {
    if (!mainRef.current || data.length === 0) return;
    const container = mainRef.current;
    const chartWidth = width ?? container.clientWidth;

    const chart = createChart(container, {
      width: chartWidth,
      height: mainH,
      ...chartTheme,
    });
    mainChartRef.current = chart;

    if (chartType === "candlestick") {
      const s = chart.addSeries(CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderUpColor: "#22c55e",
        borderDownColor: "#ef4444",
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      });
      s.setData(data as CandlestickData[]);
    } else {
      const valueData: LineData[] = data.map((d) => ({
        time: d.time,
        value: d.close,
      }));
      if (chartType === "line") {
        const s = chart.addSeries(LineSeries, {
          color: "#22c55e",
          lineWidth: 2,
        });
        s.setData(valueData);
      } else {
        const s = chart.addSeries(AreaSeries, {
          lineColor: "#22c55e",
          topColor: "#22c55e40",
          bottomColor: "#22c55e00",
          lineWidth: 2,
        });
        s.setData(valueData);
      }
    }

    if (showVolume) {
      const volData: HistogramData[] = data.map((d) => ({
        time: d.time,
        value: d.volume,
        color:
          d.close >= d.open
            ? "rgba(34,197,94,0.35)"
            : "rgba(239,68,68,0.35)",
      }));
      const v = chart.addSeries(HistogramSeries, {
        priceScaleId: "volume",
        priceFormat: { type: "volume" },
      });
      v.setData(volData);
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.75, bottom: 0 },
      });
    }

    if (showSma) {
      const configs: { period: number; color: string }[] = [
        { period: 20, color: "#f59e0b" },
        { period: 50, color: "#3b82f6" },
        { period: 200, color: "#8b5cf6" },
      ];
      for (const c of configs) {
        if (data.length >= c.period) {
          const d = computeSMA(data, c.period);
          if (d.length > 0) {
            const s = chart.addSeries(LineSeries, {
              color: c.color,
              lineWidth: 1,
            });
            s.setData(d);
          }
        }
      }
    }

    if (showBb && data.length >= 20) {
      const bb = computeBB(data, 20, 2);
      if (bb.length > 0) {
        const upper = chart.addSeries(LineSeries, {
          color: "#06b6d4",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
        });
        upper.setData(bb.map((b) => b.upper));
        const middle = chart.addSeries(LineSeries, {
          color: "#06b6d4",
          lineWidth: 1,
        });
        middle.setData(bb.map((b) => b.middle));
        const lower = chart.addSeries(LineSeries, {
          color: "#06b6d4",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
        });
        lower.setData(bb.map((b) => b.lower));
      }
    }

    chart.timeScale().fitContent();

    const observer = new ResizeObserver((entries) => {
      chart.applyOptions({ width: entries[0].contentRect.width });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      mainChartRef.current = null;
    };
  }, [data, chartType, showVolume, showSma, showBb, mainH, width]);

  useEffect(() => {
    if (!rsiRef.current || !showRsi || data.length < 15) return;
    const container = rsiRef.current;
    const chartWidth = width ?? container.clientWidth;

    const chart = createChart(container, {
      width: chartWidth,
      height: 80,
      ...chartTheme,
    });
    rsiChartRef.current = chart;

    const rsiData = computeRSI(data, 14);
    if (rsiData.length > 0) {
      const s = chart.addSeries(LineSeries, {
        color: "#a855f7",
        lineWidth: 2,
      });
      s.setData(rsiData);
      s.createPriceLine({
        price: 70,
        color: "rgba(239,68,68,0.5)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "70",
      });
      s.createPriceLine({
        price: 30,
        color: "rgba(34,197,94,0.5)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "30",
      });
    }

    chart.timeScale().fitContent();

    const observer = new ResizeObserver((entries) => {
      chart.applyOptions({ width: entries[0].contentRect.width });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      rsiChartRef.current = null;
    };
  }, [data, showRsi, width]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg bg-zinc-900/50"
        style={{ height }}
      >
        <span className="text-xs text-zinc-600">Нет данных для графика</span>
      </div>
    );
  }

  return (
    <div>
      <div ref={mainRef} />
      {showRsi && (
        <div className="mt-1">
          <div className="mb-0.5 flex items-center justify-between px-1">
            <span className="text-[10px] text-zinc-500">RSI(14)</span>
          </div>
          <div ref={rsiRef} />
        </div>
      )}
    </div>
  );
}
