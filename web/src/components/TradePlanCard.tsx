"use client";

import { formatNumber } from "../lib/format";

type TradePlan = {
  ticker: string;
  profile: string;
  current_price: number;
  entry_zone: { low: number; high: number; current: string };
  targets: Array<{ level: number; type: string; return_pct: number; rr: number }>;
  stop_loss: number;
  trailing_after: number;
  risk_reward: number;
};

const profileLabels: Record<string, string> = {
  conservative: "Консервативный",
  balanced: "Умеренный",
  aggressive: "Агрессивный",
};

export function TradePlanCard({ plan }: { plan: TradePlan }) {
  const maxTarget = Math.max(...plan.targets.map((t) => t.level), plan.entry_zone.high);
  const minPrice = Math.min(plan.stop_loss, plan.entry_zone.low);
  const range = maxTarget - minPrice || 1;

  const zoneColor =
    plan.entry_zone.current === "above"
      ? "text-red-400"
      : plan.entry_zone.current === "below"
        ? "text-emerald-400"
        : "text-amber-400";

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-light text-white">Trade Plan</h2>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-400/10 text-amber-400">
          {profileLabels[plan.profile] || plan.profile}
        </span>
      </div>

      <div className="text-xs text-gray-400 mb-4">
        Текущая цена: <span className="font-mono text-white">{formatNumber(plan.current_price)} ₽</span>
      </div>

      {/* Visual price range */}
      <div className="relative h-24 mb-4">
        {/* Background bar */}
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-2 bg-white/5 rounded-full" />

        {/* Entry zone */}
        <div
          className="absolute top-1/2 -translate-y-1/2 h-4 bg-amber-400/20 border border-amber-400/40 rounded"
          style={{
            left: `${((plan.entry_zone.low - minPrice) / range) * 100}%`,
            width: `${((plan.entry_zone.high - plan.entry_zone.low) / range) * 100}%`,
          }}
        >
          <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[9px] text-amber-400 whitespace-nowrap">
            Зона входа
          </span>
          <div className="absolute -top-3 left-0 text-[8px] text-amber-400/60">{formatNumber(plan.entry_zone.low)}</div>
          <div className="absolute -top-3 right-0 text-[8px] text-amber-400/60">{formatNumber(plan.entry_zone.high)}</div>
        </div>

        {/* Current price marker */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-0.5 h-8 bg-white z-10"
          style={{ left: `${((plan.current_price - minPrice) / range) * 100}%` }}
        >
          <div className="absolute -top-4 left-1/2 -translate-x-1/2 text-[9px] font-mono text-white whitespace-nowrap">
            {formatNumber(plan.current_price)}
          </div>
        </div>

        {/* Stop loss */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-px h-5 bg-red-500/60"
          style={{ left: `${((plan.stop_loss - minPrice) / range) * 100}%` }}
        >
          <span className="absolute top-4 left-1/2 -translate-x-1/2 text-[9px] text-red-400 whitespace-nowrap">
            SL {formatNumber(plan.stop_loss)}
          </span>
        </div>

        {/* Targets */}
        {plan.targets.map((target, i) => (
          <div
            key={i}
            className="absolute top-1/2 -translate-y-1/2 w-px h-6 bg-emerald-500/40"
            style={{ left: `${((target.level - minPrice) / range) * 100}%` }}
          >
            <span className="absolute -top-6 left-1/2 -translate-x-1/2 text-[9px] text-emerald-400 whitespace-nowrap">
              T{i + 1} {formatNumber(target.level)}
            </span>
            <span className="absolute top-4 left-1/2 -translate-x-1/2 text-[8px] text-emerald-400/60 whitespace-nowrap">
              +{target.return_pct.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      {/* Details grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-2">
        <div className="bg-white/[0.03] rounded-xl p-2.5 border border-white/5">
          <p className="text-[10px] text-gray-500">Зона входа</p>
          <p className={`text-sm font-mono ${zoneColor}`}>
            {plan.entry_zone.current === "above" ? "Выше" : plan.entry_zone.current === "below" ? "Ниже" : "Внутри"}
          </p>
        </div>
        <div className="bg-white/[0.03] rounded-xl p-2.5 border border-white/5">
          <p className="text-[10px] text-gray-500">Stop Loss</p>
          <p className="text-sm font-mono text-red-400">{formatNumber(plan.stop_loss)} ₽</p>
        </div>
        <div className="bg-white/[0.03] rounded-xl p-2.5 border border-white/5">
          <p className="text-[10px] text-gray-500">Risk/Reward</p>
          <p className="text-sm font-mono text-emerald-400">1:{plan.risk_reward.toFixed(1)}</p>
        </div>
        <div className="bg-white/[0.03] rounded-xl p-2.5 border border-white/5">
          <p className="text-[10px] text-gray-500">Trailing after</p>
          <p className="text-sm font-mono text-white">{plan.trailing_after > 0 ? `T${plan.trailing_after}` : "—"}</p>
        </div>
      </div>

      {/* Targets table */}
      {plan.targets.length > 0 && (
        <div className="mt-4">
          <p className="text-[10px] text-gray-500 font-mono mb-2">Цели</p>
          <div className="space-y-1">
            {plan.targets.map((target, i) => (
              <div key={i} className="flex items-center justify-between bg-white/[0.03] rounded-lg px-3 py-2 border border-white/5">
                <span className="text-xs text-gray-400">T{i + 1} — {target.type === "tp" ? "Take Profit" : target.type}</span>
                <span className="text-xs font-mono text-emerald-400">{formatNumber(target.level)} ₽ (+{target.return_pct.toFixed(1)}%, RR {target.rr.toFixed(1)})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-[10px] text-gray-600 mt-3">
        P&L рассчитан для профиля &quot;{profileLabels[plan.profile] || plan.profile}&quot;. Рынок может отличаться.
      </p>
    </section>
  );
}
