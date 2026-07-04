"use client";

type RiskData = Record<string, unknown>;

export function RiskMetricsCard({ data, isLoading }: { data: RiskData | null; isLoading: boolean }) {
  if (isLoading) {
    return (
      <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm animate-pulse">
        <div className="h-4 w-20 bg-white/10 rounded mb-4" />
        <div className="grid grid-cols-3 gap-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 bg-white/5 rounded-xl" />
          ))}
        </div>
      </section>
    );
  }

  if (!data) return null;

  const sectorExposure = data.sector_exposure as Record<string, number> | undefined;

  const metrics: Array<{ label: string; value: string; positive: boolean }> = [];

  if (data.var_95 !== undefined) {
    const v = data.var_95 as number;
    metrics.push({ label: "VaR 95%", value: `${(v * 100).toFixed(2)}%`, positive: v >= 0 });
  }
  if (data.cvar_95 !== undefined) {
    const v = data.cvar_95 as number;
    metrics.push({ label: "CVaR 95%", value: `${(v * 100).toFixed(2)}%`, positive: v >= 0 });
  }
  if (data.volatility !== undefined) {
    const v = data.volatility as number;
    metrics.push({ label: "Волатильность", value: `${(v * 100).toFixed(2)}%`, positive: true });
  }
  if (data.sharpe_ratio !== undefined) {
    const v = data.sharpe_ratio as number;
    metrics.push({ label: "Sharpe", value: v.toFixed(2), positive: v >= 1 });
  }
  if (data.max_drawdown !== undefined) {
    const v = data.max_drawdown as number;
    metrics.push({ label: "Max Drawdown", value: `${(v * 100).toFixed(2)}%`, positive: v >= -0.2 });
  }
  if (data.beta !== undefined) {
    metrics.push({ label: "Beta", value: (data.beta as number).toFixed(2), positive: true });
  }

  if (metrics.length === 0 && !sectorExposure) return null;

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4">Риск-метрики</h2>
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {metrics.map((m) => (
            <div key={m.label} className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <p className="text-[10px] text-gray-500 font-mono mb-1">{m.label}</p>
              <p className={`text-lg font-mono font-light ${m.positive ? "text-emerald-400" : "text-red-400"}`}>
                {m.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {sectorExposure && (
        <div className="mt-4">
          <p className="text-[10px] text-gray-500 font-mono mb-2">Секторальная экспозиция</p>
          <div className="space-y-1.5">
            {Object.entries(sectorExposure)
              .sort(([, a], [, b]) => b - a)
              .map(([sector, pct]) => (
                <div key={sector} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-24 truncate">{sector}</span>
                  <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-amber-400/60 rounded-full"
                      style={{ width: `${Math.min(pct * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-white w-12 text-right">{(pct * 100).toFixed(0)}%</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </section>
  );
}
