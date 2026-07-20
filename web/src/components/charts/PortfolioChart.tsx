"use client";

import { useId } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";

export interface PortfolioPoint {
  time: string;
  value: number;
}

export interface AllocationEntry {
  sector: string;
  value: number;
  color?: string;
}

interface Props {
  data: PortfolioPoint[];
  showAllocation?: boolean;
  allocation?: AllocationEntry[];
  height?: number;
}

const SECTOR_COLORS = [
  "#22c55e",
  "#3b82f6",
  "#f59e0b",
  "#a855f7",
  "#06b6d4",
  "#ef4444",
  "#ec4899",
  "#14b8a6",
];

function formatValue(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
}

export default function PortfolioChart({
  data,
  showAllocation = false,
  allocation = [],
  height = 320,
}: Props) {
  const gradientId = useId();

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg bg-zinc-900/50"
        style={{ height }}
      >
        <span className="text-xs text-zinc-600">Нет данных</span>
      </div>
    );
  }

  const isPositive =
    data.length > 1 ? data[data.length - 1].value >= data[0].value : true;
  const lineColor = isPositive ? "#22c55e" : "#ef4444";

  return (
    <div className="space-y-4">
      <div style={{ height: showAllocation ? height : height }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={lineColor} stopOpacity={0.3} />
                <stop offset="95%" stopColor={lineColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10, fill: "#a1a1aa" }}
              axisLine={{ stroke: "#27272a" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#a1a1aa" }}
              axisLine={{ stroke: "#27272a" }}
              tickLine={false}
              tickFormatter={formatValue}
            />
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #27272a",
                borderRadius: "8px",
                fontSize: "12px",
                color: "#fff",
              }}
              formatter={(value) => {
                if (value == null) return ["", ""];
                return [formatValue(value as number), "Стоимость"];
              }}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={lineColor}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {showAllocation && allocation.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
            Распределение по секторам
          </h4>
          <div className="flex flex-wrap items-center gap-4">
            <ResponsiveContainer width={180} height={180}>
              <PieChart>
                <Pie
                  data={allocation}
                  dataKey="value"
                  nameKey="sector"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  innerRadius={50}
                  paddingAngle={2}
                >
                  {allocation.map((entry, i) => (
                    <Cell
                      key={entry.sector}
                      fill={entry.color ?? SECTOR_COLORS[i % SECTOR_COLORS.length]}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "#18181b",
                    border: "1px solid #27272a",
                    borderRadius: "8px",
                    fontSize: "12px",
                    color: "#fff",
                  }}
                  formatter={(value) => {
                    if (value == null) return ["", ""];
                    return [formatValue(value as number), "Стоимость"];
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="space-y-1">
              {allocation.map((entry, i) => (
                <div key={entry.sector} className="flex items-center gap-2 text-xs">
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{
                      backgroundColor:
                        entry.color ?? SECTOR_COLORS[i % SECTOR_COLORS.length],
                    }}
                  />
                  <span className="text-zinc-400">{entry.sector}</span>
                  <span className="text-zinc-200">{formatValue(entry.value)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
