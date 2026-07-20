"use client";

import { useState, useMemo, useSyncExternalStore } from "react";
import TradingViewChart from "./TradingViewChart";
import type { OHLCVData } from "./TradingViewChart";

export type ChartInterval = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y" | "ALL";
export type ChartStyle = "candlestick" | "line" | "area";

const INTERVALS: ChartInterval[] = ["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"];

const INTERVAL_MS: Record<ChartInterval, number> = {
  "1D": 86_400_000,
  "1W": 604_800_000,
  "1M": 2_592_000_000,
  "3M": 7_776_000_000,
  "6M": 15_552_000_000,
  "1Y": 31_536_000_000,
  ALL: Infinity,
};

const BTN_CLASS =
  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors";
const BTN_ACTIVE = "bg-amber-400/20 text-amber-400";
const BTN_INACTIVE = "text-zinc-500 hover:text-zinc-200";

function subscribeToNow(cb: () => void): () => void {
  const id = setInterval(cb, 60_000);
  return () => clearInterval(id);
}

function getNow(): number {
  return Date.now();
}

interface Props {
  data: OHLCVData[];
  height?: number;
}

export default function AdvancedMarketChart({ data, height = 400 }: Props) {
  const [interval, setInterval] = useState<ChartInterval>("1M");
  const [showSma, setShowSma] = useState(false);
  const [showBb, setShowBb] = useState(false);
  const [showRsi, setShowRsi] = useState(false);
  const [showVolume, setShowVolume] = useState(true);
  const [chartType, setChartType] = useState<ChartStyle>("candlestick");

  const now = useSyncExternalStore(subscribeToNow, getNow);

  const filtered = useMemo(() => {
    const cutoff = now - INTERVAL_MS[interval];
    return interval === "ALL"
      ? data
      : data.filter((d) => {
          const t = new Date(d.time).getTime();
          return !isNaN(t) && t >= cutoff;
        });
  }, [data, interval, now]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-0.5 rounded-lg bg-zinc-900 p-0.5">
          {INTERVALS.map((iv) => (
            <button
              key={iv}
              type="button"
              onClick={() => setInterval(iv)}
              className={`${BTN_CLASS} ${
                interval === iv ? BTN_ACTIVE : BTN_INACTIVE
              }`}
            >
              {iv}
            </button>
          ))}
        </div>

        <div className="h-5 w-px bg-zinc-700" />

        <div className="flex items-center gap-0.5 rounded-lg bg-zinc-900 p-0.5">
          <button
            type="button"
            onClick={() => setShowSma((v) => !v)}
            className={`${BTN_CLASS} ${showSma ? "bg-amber-400/20 text-amber-400" : BTN_INACTIVE}`}
          >
            SMA
          </button>
          <button
            type="button"
            onClick={() => setShowBb((v) => !v)}
            className={`${BTN_CLASS} ${showBb ? "bg-cyan-400/20 text-cyan-400" : BTN_INACTIVE}`}
          >
            BB
          </button>
          <button
            type="button"
            onClick={() => setShowRsi((v) => !v)}
            className={`${BTN_CLASS} ${showRsi ? "bg-purple-400/20 text-purple-400" : BTN_INACTIVE}`}
          >
            RSI
          </button>
          <button
            type="button"
            onClick={() => setShowVolume((v) => !v)}
            className={`${BTN_CLASS} ${showVolume ? "bg-blue-400/20 text-blue-400" : BTN_INACTIVE}`}
          >
            Vol
          </button>
        </div>

        <div className="h-5 w-px bg-zinc-700" />

        <div className="flex items-center gap-0.5 rounded-lg bg-zinc-900 p-0.5">
          {(["candlestick", "line", "area"] as const).map((ct) => (
            <button
              key={ct}
              type="button"
              onClick={() => setChartType(ct)}
              className={`${BTN_CLASS} ${
                chartType === ct ? BTN_ACTIVE : BTN_INACTIVE
              }`}
            >
              {ct === "candlestick"
                ? " свечи"
                : ct === "line"
                  ? " линия"
                  : " область"}
            </button>
          ))}
        </div>
      </div>

      <TradingViewChart
        data={filtered}
        height={height}
        overlays={{
          sma: showSma,
          bb: showBb,
          rsi: showRsi,
          volume: showVolume,
        }}
        chartType={chartType}
      />
    </div>
  );
}
