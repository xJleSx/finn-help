"use client";

import type { GeoRisk } from "./types";

export default function GeoRiskPanel({ geoHistory }: { geoHistory: GeoRisk[] }) {
  const latestGeo = geoHistory[geoHistory.length - 1];
  if (!latestGeo) return null;

  return (
    <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h3 className="text-sm font-light text-white mb-3">Геополитический риск</h3>
      <div className="flex items-center gap-3 mb-3">
        <div className={`w-2.5 h-2.5 rounded-full ${latestGeo.score > 7 ? "bg-red-500" : latestGeo.score > 5 ? "bg-amber-400" : "bg-emerald-500"} animate-pulse`} />
        <span className="text-3xl font-mono font-light text-white">{latestGeo.score.toFixed(1)}</span>
        <span className="text-xs text-gray-600">/10</span>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${latestGeo.score > 7 ? "bg-red-500" : latestGeo.score > 5 ? "bg-amber-400" : "bg-emerald-500"}`}
          style={{ width: `${latestGeo.score * 10}%` }} />
      </div>
      {geoHistory.length > 1 && (
        <div className="mt-4">
          <p className="text-[10px] text-gray-600 mb-1.5">14 дней</p>
          <div className="flex items-end gap-0.5 h-10">
            {geoHistory.map((g, i) => (
              <div key={i}
                className={`flex-1 rounded-t ${g.score > 7 ? "bg-red-500/40" : g.score > 5 ? "bg-amber-400/40" : "bg-emerald-500/40"}`}
                style={{ height: `${g.score * 10}%` }}
                title={`${g.date}: ${g.score.toFixed(1)}`} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
