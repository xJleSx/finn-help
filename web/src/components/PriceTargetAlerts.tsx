"use client";

import Link from "next/link";

type PriceTarget = {
  ticker: string;
  current_price: number;
  target_price: number;
  target_type: string;
  triggered_pct: number;
};

export function PriceTargetAlerts({ targets }: { targets: PriceTarget[] }) {
  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-3">Ценовые цели</h2>
      <div className="space-y-2">
        {targets.map((pt, i) => {
          const triggered = pt.triggered_pct >= 100;
          return (
            <div
              key={i}
              className={`flex items-center gap-4 bg-white/[0.03] rounded-xl px-4 py-3 border ${
                triggered ? "border-emerald-500/20" : "border-white/5"
              }`}
            >
              <Link
                href={`/instruments/${pt.ticker}`}
                className="font-mono text-xs text-amber-400/80 hover:text-amber-400 transition"
              >
                {pt.ticker}
              </Link>
              <div className="flex-1">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-500">{pt.current_price.toFixed(2)} ₽</span>
                  <span className="text-gray-400 font-mono">
                    → {pt.target_price.toFixed(2)} ₽
                  </span>
                  <span className={triggered ? "text-emerald-400 font-mono" : "text-amber-400 font-mono"}>
                    {pt.triggered_pct.toFixed(0)}%
                  </span>
                </div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      triggered ? "bg-emerald-500" : "bg-amber-400"
                    }`}
                    style={{ width: `${Math.min(pt.triggered_pct, 100)}%` }}
                  />
                </div>
              </div>
              <span className="text-[10px] text-gray-600 min-w-[60px] text-right">
                {pt.target_type}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
