"use client";

import type { News } from "./types";

export default function NewsPanel({ news }: { news: News[] }) {
  return (
    <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h3 className="text-sm font-light text-white mb-3">Последние новости</h3>
      <div className="space-y-2.5">
        {news.map((n) => (
          <div key={n.id} className="border-b border-white/5 pb-2.5 last:border-0">
            <a href={n.url} target="_blank" className="text-xs text-gray-300 hover:text-amber-400 transition line-clamp-2" rel="noreferrer">
              {n.title}
            </a>
            <p className="text-[10px] text-gray-600 mt-1">{n.source} — {n.published_at?.slice(0, 10)}</p>
          </div>
        ))}
        {news.length === 0 && <p className="text-xs text-gray-600">Новости не загружены</p>}
      </div>
    </div>
  );
}
