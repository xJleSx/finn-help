"use client";

export function AlertAnalytics({ data }: { data: Record<string, unknown> }) {
  const byCategory = data.by_category as Record<string, number> | undefined;
  const dailyCounts = data.daily_counts as Record<string, number> | undefined;

  const metrics: Array<{ label: string; value: string }> = [];

  if (data.total_alerts !== undefined) {
    metrics.push({ label: "Всего алертов", value: String(data.total_alerts) });
  }
  if (data.avg_severity !== undefined) {
    metrics.push({ label: "Средняя важность", value: (data.avg_severity as number).toFixed(2) });
  }
  if (data.high_count !== undefined) {
    metrics.push({ label: "Высокой важности", value: String(data.high_count) });
  }
  if (byCategory) {
    const entries = Object.entries(byCategory);
    const topCat = entries.sort(([, a], [, b]) => b - a)[0];
    if (topCat) {
      metrics.push({ label: `Топ категория: ${topCat[0]}`, value: String(topCat[1]) });
    }
  }

  if (metrics.length === 0 && !byCategory && !dailyCounts) return null;

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4">Аналитика алертов</h2>
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {metrics.map((m) => (
            <div key={m.label} className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <p className="text-[10px] text-gray-500 font-mono mb-1">{m.label}</p>
              <p className="text-lg font-mono font-light text-white">{m.value}</p>
            </div>
          ))}
        </div>
      )}

      {byCategory && (
        <div className="mt-4">
          <p className="text-[10px] text-gray-500 font-mono mb-2">По категориям</p>
          <div className="space-y-1.5">
            {Object.entries(byCategory)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 10)
              .map(([category, count]) => {
                const maxVal = Math.max(...Object.values(byCategory), 1);
                return (
                  <div key={category} className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 flex-1 truncate">{category}</span>
                    <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden max-w-[120px]">
                      <div className="h-full bg-amber-400/60 rounded-full" style={{ width: `${(count / maxVal) * 100}%` }} />
                    </div>
                    <span className="text-xs font-mono text-white w-8 text-right">{count}</span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {dailyCounts && (
        <div className="mt-4">
          <p className="text-[10px] text-gray-500 font-mono mb-2">По дням</p>
          <div className="flex items-end gap-1 h-12">
            {Object.entries(dailyCounts)
              .slice(-30)
              .map(([date, count]) => {
                const maxCount = Math.max(...Object.values(dailyCounts), 1);
                return (
                  <div
                    key={date}
                    className="flex-1 bg-amber-400/40 rounded-t"
                    style={{ height: `${(count / maxCount) * 100}%` }}
                    title={`${date}: ${count}`}
                  />
                );
              })}
          </div>
        </div>
      )}
    </section>
  );
}
