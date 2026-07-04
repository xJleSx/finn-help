"use client";

export function SignalBadge({ signal }: { signal: Record<string, unknown> }) {
  const fused = signal.fused as string | undefined;
  const confidence = signal.confidence as number | undefined;

  const colorMap: Record<string, string> = {
    buy: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    sell: "bg-red-500/20 text-red-400 border-red-500/30",
    hold: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    strong_buy: "bg-emerald-500/30 text-emerald-300 border-emerald-500/50",
    strong_sell: "bg-red-500/30 text-red-300 border-red-500/50",
  };

  const label = fused?.toLowerCase() || "hold";
  const displayLabel = fused
    ? fused.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())
    : "Hold";

  return (
    <div className="flex items-center gap-3">
      <div className={`px-3 py-1.5 rounded-lg border text-xs font-medium ${colorMap[label] || colorMap.hold}`}>
        {displayLabel}
      </div>
      {confidence !== undefined && (
        <div className="flex items-center gap-1.5">
          <div className="h-1.5 w-16 bg-white/5 rounded-full overflow-hidden">
            <div
              className="h-full bg-amber-400 rounded-full transition-all"
              style={{ width: `${Math.min(confidence * 100, 100)}%` }}
            />
          </div>
          <span className="text-xs font-mono text-gray-400">{(confidence * 100).toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
}
