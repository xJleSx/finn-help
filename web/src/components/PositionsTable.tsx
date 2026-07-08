"use client";

import Link from "next/link";
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

export function PositionsTable({ positions, isLoading }: { positions: Position[]; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm animate-pulse">
        <div className="h-4 w-24 bg-white/10 rounded mb-4" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-10 bg-white/5 rounded mb-2" />
        ))}
      </div>
    );
  }

  if (positions.length === 0) return null;

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4">Позиции</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-600 border-b border-white/5">
              <th className="text-left py-2 font-mono text-xs">Тикер</th>
              <th className="text-right py-2 font-mono text-xs">Кол-во</th>
              <th className="text-right py-2 font-mono text-xs">Средняя</th>
              <th className="text-right py-2 font-mono text-xs">Текущая</th>
              <th className="text-right py-2 font-mono text-xs">Стоимость</th>
              <th className="text-right py-2 font-mono text-xs">P&L</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const isPositive = (p.profit_pct ?? 0) >= 0;
              return (
                <tr
                  key={p.id}
                  className="border-b border-white/5 hover:bg-white/[0.02] transition"
                >
                  <td className="py-2.5">
                    <Link
                      href={`/instruments/${p.ticker}`}
                      className="font-mono text-amber-400/80 text-xs hover:text-amber-400 transition"
                    >
                      {p.ticker}
                    </Link>
                  </td>
                  <td className="py-2.5 text-right font-mono text-xs text-white">{p.quantity}</td>
                  <td className="py-2.5 text-right font-mono text-xs text-gray-400">
                    {p.avg_price ? `${p.avg_price.toFixed(2)} ₽` : "—"}
                  </td>
                  <td className="py-2.5 text-right font-mono text-xs text-white">
                    {p.current_price ? `${p.current_price.toFixed(2)} ₽` : "—"}
                  </td>
                  <td className="py-2.5 text-right font-mono text-xs text-white">
                    {formatCurrency(p.value)}
                  </td>
                  <td className={`py-2.5 text-right font-mono text-xs ${isPositive ? "text-emerald-400" : "text-red-400"}`}>
                    {p.profit_pct !== null ? `${isPositive ? "+" : ""}${p.profit_pct.toFixed(2)}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
