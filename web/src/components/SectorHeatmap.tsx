"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function SectorHeatmap() {
  const [sectors, setSectors] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/sectors/performance?days=30`)
      .then((r) => r.json())
      .then((data) => { setSectors(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const entries = Object.entries(sectors).sort((a, b) => b[1] - a[1]);
  if (loading || entries.length === 0) return null;

  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 0.01);

  return (
    <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4"><span className="text-amber-400 font-medium">Сектора</span> — доходность за 30д</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {entries.map(([name, ret]) => {
          const intensity = Math.abs(ret) / maxAbs;
          const isPositive = ret >= 0;
          const r = isPositive ? 0 : Math.round(220 * intensity);
          const g = isPositive ? Math.round(200 * intensity) : 0;
          const b = isPositive ? 0 : 0;
          return (
            <div key={name} className="rounded-xl p-3 border border-white/5 text-center transition hover:scale-[1.02]"
              style={{ background: `rgba(${r}, ${g}, ${b}, 0.15)`, borderColor: isPositive ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)" }}>
              <p className="text-[10px] text-gray-400 truncate">{name}</p>
              <p className={`text-sm font-mono mt-0.5 ${isPositive ? "text-emerald-400" : "text-red-400"}`}>
                {ret > 0 ? "+" : ""}{(ret * 100).toFixed(1)}%
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
