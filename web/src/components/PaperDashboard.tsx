"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api-client";

export function PaperDashboard() {
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");

  const { data: status, isLoading } = useQuery({
    queryKey: ["paper-status"],
    queryFn: () => api.paper.status(),
    refetchInterval: 30_000,
  });

  const { data: metrics } = useQuery({
    queryKey: ["paper-metrics"],
    queryFn: () => api.paper.metrics(),
    refetchInterval: 60_000,
  });

  const { data: orders } = useQuery({
    queryKey: ["paper-orders"],
    queryFn: () => api.paper.orders(20),
    refetchInterval: 15_000,
  });

  const { data: equityCurve } = useQuery({
    queryKey: ["paper-equity-curve"],
    queryFn: () => api.paper.equityCurve(),
    refetchInterval: 30_000,
  });

  const orderMutation = useMutation({
    mutationFn: (body: { ticker: string; direction: string; quantity: number; price?: number }) =>
      api.paper.order(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper-status"] });
      queryClient.invalidateQueries({ queryKey: ["paper-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["paper-orders"] });
      setTicker("");
      setQuantity("");
      setPrice("");
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => api.paper.reset(1_000_000),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper-status"] });
      queryClient.invalidateQueries({ queryKey: ["paper-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["paper-orders"] });
    },
  });

  if (isLoading) {
    return (
      <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
        <p className="text-xs text-gray-500">Загрузка Paper Dashboard...</p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      {status && (
        <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-light text-white">Paper Trading</h2>
            <button
              onClick={() => resetMutation.mutate()}
              className="px-3 py-1.5 rounded-xl text-xs font-medium bg-red-400/20 text-red-400 hover:bg-red-400/30 transition"
            >
              Сбросить
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <p className="text-[10px] text-gray-500 font-mono mb-1">Баланс</p>
              <p className="text-lg font-mono font-light text-white">{status.balance?.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽</p>
            </div>
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <p className="text-[10px] text-gray-500 font-mono mb-1">Equity</p>
              <p className="text-lg font-mono font-light text-white">{status.total_equity?.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽</p>
            </div>
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <p className="text-[10px] text-gray-500 font-mono mb-1">Доходность</p>
              <p className={`text-lg font-mono font-light ${(status.total_return_pct || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {(status.total_return_pct * 100)?.toFixed(2)}%
              </p>
            </div>
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <p className="text-[10px] text-gray-500 font-mono mb-1">Позиций</p>
              <p className="text-lg font-mono font-light text-white">{status.positions?.length || 0}</p>
            </div>
          </div>

          {status.positions?.length > 0 && (
            <div className="mb-4">
              <h3 className="text-xs text-gray-500 mb-2">Открытые позиции</h3>
              <div className="space-y-1.5">
                {status.positions.map((p: { ticker: string; quantity: number; avg_price: number; value: number }) => (
                  <div key={p.ticker} className="flex items-center justify-between bg-white/[0.03] rounded-xl px-4 py-2.5 border border-white/5">
                    <span className="font-mono text-xs text-white">{p.ticker}</span>
                    <div className="flex gap-4 text-xs font-mono">
                      <span className="text-gray-500">{p.quantity.toFixed(0)} шт</span>
                      <span className="text-gray-400">@ {p.avg_price.toFixed(2)}</span>
                      <span className="text-white">{p.value.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="border-t border-white/10 pt-4">
            <h3 className="text-xs text-gray-500 mb-2">Новая сделка</h3>
            <div className="flex flex-wrap gap-2 items-end">
              <div>
                <label className="text-[10px] text-gray-600 block mb-0.5">Тикер</label>
                <input
                  type="text"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  placeholder="SBER"
                  className="bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/30 font-mono w-24"
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-600 block mb-0.5">Кол-во</label>
                <input
                  type="number"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="10"
                  className="bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/30 font-mono w-24"
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-600 block mb-0.5">Цена</label>
                <input
                  type="number"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="~ рыночная"
                  className="bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/30 font-mono w-28"
                />
              </div>
              <button
                onClick={() => {
                  const qty = parseFloat(quantity);
                  if (!ticker.trim() || !qty || qty <= 0) return;
                  orderMutation.mutate({
                    ticker: ticker.trim(),
                    direction: "BUY",
                    quantity: qty,
                    price: price ? parseFloat(price) : undefined,
                  });
                }}
                disabled={orderMutation.isPending || !ticker.trim() || !quantity}
                className="px-4 py-1.5 rounded-xl text-xs font-medium bg-emerald-400/20 text-emerald-400 hover:bg-emerald-400/30 transition disabled:opacity-40"
              >
                Купить
              </button>
              <button
                onClick={() => {
                  const qty = parseFloat(quantity);
                  if (!ticker.trim() || !qty || qty <= 0) return;
                  orderMutation.mutate({
                    ticker: ticker.trim(),
                    direction: "SELL",
                    quantity: qty,
                    price: price ? parseFloat(price) : undefined,
                  });
                }}
                disabled={orderMutation.isPending || !ticker.trim() || !quantity}
                className="px-4 py-1.5 rounded-xl text-xs font-medium bg-red-400/20 text-red-400 hover:bg-red-400/30 transition disabled:opacity-40"
              >
                Продать
              </button>
              <button
                onClick={() => {
                  const qty = parseFloat(quantity);
                  if (!ticker.trim() || !qty || qty <= 0) return;
                  orderMutation.mutate({
                    ticker: ticker.trim(),
                    direction: "SHORT",
                    quantity: qty,
                    price: price ? parseFloat(price) : undefined,
                  });
                }}
                disabled={orderMutation.isPending || !ticker.trim() || !quantity}
                className="px-4 py-1.5 rounded-xl text-xs font-medium bg-orange-400/20 text-orange-400 hover:bg-orange-400/30 transition disabled:opacity-40"
              >
                Short
              </button>
              <button
                onClick={() => {
                  const qty = parseFloat(quantity);
                  if (!ticker.trim() || !qty || qty <= 0) return;
                  orderMutation.mutate({
                    ticker: ticker.trim(),
                    direction: "COVER",
                    quantity: qty,
                    price: price ? parseFloat(price) : undefined,
                  });
                }}
                disabled={orderMutation.isPending || !ticker.trim() || !quantity}
                className="px-4 py-1.5 rounded-xl text-xs font-medium bg-violet-400/20 text-violet-400 hover:bg-violet-400/30 transition disabled:opacity-40"
              >
                Cover
              </button>
            </div>
          </div>
        </section>
      )}

      {metrics && (
        <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
          <h2 className="text-sm font-light text-white mb-4">Метрики производительности</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {(() => {
              const m = metrics as Record<string, number>;
              const items = [
                { label: "Sharpe", value: m.sharpe?.toFixed(2), color: "text-white" },
                { label: "Sortino", value: m.sortino?.toFixed(2), color: "text-white" },
                { label: "Calmar", value: m.calmar?.toFixed(2), color: "text-white" },
                { label: "Max DD", value: m.max_drawdown != null ? `${(m.max_drawdown * 100).toFixed(1)}%` : "-", color: m.max_drawdown < -0.2 ? "text-red-400" : "text-amber-400" },
                { label: "Win Rate", value: m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : "-", color: "text-emerald-400" },
                { label: "Profit Factor", value: m.profit_factor?.toFixed(2), color: "text-white" },
                { label: "Total Return", value: m.total_return != null ? `${(m.total_return * 100).toFixed(1)}%` : "-", color: (m.total_return || 0) >= 0 ? "text-emerald-400" : "text-red-400" },
                { label: "Annual Return", value: m.annual_return != null ? `${(m.annual_return * 100).toFixed(1)}%` : "-", color: (m.annual_return || 0) >= 0 ? "text-emerald-400" : "text-red-400" },
                { label: "Volatility", value: m.volatility != null ? `${(m.volatility * 100).toFixed(1)}%` : "-", color: "text-white" },
                { label: "VaR(95%)", value: m.var_95 != null ? `${(m.var_95 * 100).toFixed(1)}%` : "-", color: "text-red-400" },
                { label: "CVaR(95%)", value: m.cvar_95 != null ? `${(m.cvar_95 * 100).toFixed(1)}%` : "-", color: "text-red-400" },
                { label: "Сделок", value: String(m.n_trades ?? 0), color: "text-white" },
              ];
              return items.map((item) => (
                <div key={item.label} className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
                  <p className="text-[10px] text-gray-500 font-mono mb-1">{item.label}</p>
                  <p className={`text-lg font-mono font-light ${item.color}`}>{item.value}</p>
                </div>
              ));
            })()}
          </div>
        </section>
      )}

      {equityCurve && equityCurve.equity_curve && equityCurve.equity_curve.length > 1 && (
        <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
          <h2 className="text-sm font-light text-white mb-4">Equity Curve</h2>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityCurve.equity_curve.map((v: number, i: number) => ({ i, v }))}>
                <defs>
                  <linearGradient id="eqGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#fbbf24" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#fbbf24" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="i" hide />
                <YAxis domain={["auto", "auto"]} hide />
                <Tooltip
                  formatter={(value: unknown) => [(value as number).toLocaleString("ru-RU", { maximumFractionDigits: 0 }) + " ₽"]}
                  contentStyle={{ background: "#1a1a2e", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 12 }}
                  labelStyle={{ color: "#9ca3af" }}
                />
                <Area type="monotone" dataKey="v" stroke="#fbbf24" strokeWidth={2} fill="url(#eqGradient)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {orders && orders.trades && (orders.trades as Record<string, unknown>[]).length > 0 && (
        <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
          <h2 className="text-sm font-light text-white mb-4">История сделок</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-gray-500 border-b border-white/10">
                  <th className="text-left py-2 pr-3">Время</th>
                  <th className="text-left py-2 pr-3">Тикер</th>
                  <th className="text-left py-2 pr-3">Напр.</th>
                  <th className="text-right py-2 pr-3">Кол-во</th>
                  <th className="text-right py-2 pr-3">Цена</th>
                  <th className="text-right py-2 pr-3">P&L</th>
                  <th className="text-right py-2 pr-3">Баланс</th>
                </tr>
              </thead>
              <tbody>
                {(orders.trades as Record<string, unknown>[]).slice().reverse().map((t, i) => (
                  <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02]">
                    <td className="py-2 pr-3 text-gray-500">{(t.timestamp as string)?.slice(11, 19)}</td>
                    <td className="py-2 pr-3 text-white">{t.ticker as string}</td>
                    <td className={`py-2 pr-3 ${t.direction === "BUY" ? "text-emerald-400" : t.direction === "SHORT" ? "text-orange-400" : t.direction === "COVER" ? "text-violet-400" : "text-red-400"}`}>{t.direction as string}</td>
                    <td className="py-2 pr-3 text-right text-gray-300">{(t.quantity as number).toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right text-gray-300">{(t.price as number)?.toFixed(2)}</td>
                    <td className={`py-2 pr-3 text-right ${((t.pnl as number) || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{t.pnl ? `${(t.pnl as number) >= 0 ? "+" : ""}${(t.pnl as number).toFixed(0)}` : "-"}</td>
                    <td className="py-2 pr-3 text-right text-gray-300">{(t.balance_after as number)?.toLocaleString("ru-RU", { maximumFractionDigits: 0 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
