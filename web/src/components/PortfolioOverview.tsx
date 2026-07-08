"use client";

import { useMemo } from "react";
import { formatCurrency } from "../lib/format";

type Position = {
  id: number;
  ticker: string;
  quantity: number;
  avg_price: number | null;
  current_price: number | null;
  value: number;
  profit_pct: number | null;
};

export function PortfolioOverview({ positions, isLoading }: { positions: Position[]; isLoading: boolean }) {
  const summary = useMemo(() => {
    const totalValue = positions.reduce((s, p) => s + p.value, 0);
    const totalCost = positions.reduce((s, p) => s + (p.avg_price ?? 0) * p.quantity, 0);
    const totalPnL = totalValue - totalCost;
    const totalPnLPct = totalCost > 0 ? (totalPnL / totalCost) * 100 : 0;
    const gainers = positions.filter((p) => (p.profit_pct ?? 0) > 0).length;
    const losers = positions.filter((p) => (p.profit_pct ?? 0) < 0).length;
    return { totalValue, totalCost, totalPnL, totalPnLPct, gainers, losers, count: positions.length };
  }, [positions]);

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 animate-pulse">
            <div className="h-3 w-20 bg-white/10 rounded mb-3" />
            <div className="h-6 w-28 bg-white/10 rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (summary.count === 0) {
    return (
      <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-6 backdrop-blur-sm text-center">
        <p className="text-gray-500 text-sm">Портфель пуст</p>
        <p className="text-xs text-gray-600 mt-1">Добавьте позиции через страницу инструментов</p>
      </div>
    );
  }

  const cards = [
    { label: "Стоимость портфеля", value: formatCurrency(summary.totalValue), color: "text-white" },
    { label: "P&L", value: `${summary.totalPnL >= 0 ? "+" : ""}${formatCurrency(summary.totalPnL)}`, color: summary.totalPnL >= 0 ? "text-emerald-400" : "text-red-400" },
    { label: "Доходность", value: `${summary.totalPnLPct >= 0 ? "+" : ""}${summary.totalPnLPct.toFixed(2)}%`, color: summary.totalPnLPct >= 0 ? "text-emerald-400" : "text-red-400" },
    { label: "Позиции", value: `${summary.count} (${summary.gainers}↑ ${summary.losers}↓)`, color: "text-white" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm transition hover:border-white/20"
        >
          <p className="text-xs text-gray-500 mb-1.5 font-mono">{card.label}</p>
          <p className={`text-xl font-mono font-light ${card.color}`}>{card.value}</p>
        </div>
      ))}
    </div>
  );
}
