"use client";

import { useState } from "react";
import Link from "next/link";

type AlertItem = Record<string, unknown>;

const priorityColors: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400 border-red-500/30",
  high: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  low: "bg-blue-500/20 text-blue-400 border-blue-500/30",
};

const priorityIcons: Record<string, string> = {
  critical: "\u26D4",
  high: "\u26A0",
  medium: "\u2139",
  low: "\u2139",
};

function str(v: unknown): string {
  if (v == null) return "";
  return String(v);
}

function num(v: unknown): number | undefined {
  if (typeof v === "number") return v;
  return undefined;
}

export function AlertList({ alerts, isLoading }: { alerts: AlertItem[]; isLoading: boolean }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-16 bg-white/5 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-8 backdrop-blur-sm text-center">
        <p className="text-gray-500 text-sm">Нет алертов</p>
        <p className="text-xs text-gray-600 mt-1">Обновите данные или добавьте новые инструменты</p>
      </div>
    );
  }

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl overflow-hidden backdrop-blur-sm">
      <div className="px-5 py-3 border-b border-white/5">
        <h2 className="text-sm font-light text-white">Последние алерты</h2>
      </div>
      <div className="divide-y divide-white/5">
        {alerts.map((alert, idx) => {
          const id = num(alert.news_id) ?? idx;
          const priority = (str(alert.priority) || "low").toLowerCase();
          const isExpanded = expandedId === id;
          const ticker = str(alert.ticker);
          const title = str(alert.title);
          const category = str(alert.category);
          const reason = str(alert.reason);
          const sourceName = str(alert.source_name);
          const subcategory = str(alert.subcategory);
          const publishedAt = str(alert.published_at);
          const impactConfidence = num(alert.impact_confidence);
          const anomalyScore = num(alert.anomaly_score);
          const predictedReturn = num(alert.predicted_return);

          return (
            <div key={id} className="p-4 hover:bg-white/[0.02] transition">
              <div
                className="flex items-start gap-3 cursor-pointer"
                onClick={() => setExpandedId(isExpanded ? null : id)}
              >
                <span className="text-sm mt-0.5">{priorityIcons[priority] || "\u2139"}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {ticker && (
                      <Link
                        href={`/instruments/${ticker}`}
                        className="font-mono text-xs text-amber-400/80 hover:text-amber-400 transition"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {ticker}
                      </Link>
                    )}
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium border ${priorityColors[priority] || priorityColors.low}`}>
                      {priority.toUpperCase()}
                    </span>
                    {category && (
                      <span className="text-[10px] text-gray-600">{category}</span>
                    )}
                  </div>
                  <p className="text-sm text-gray-300 line-clamp-2">{title}</p>
                  <div className="flex items-center gap-3 mt-1">
                    {publishedAt && (
                      <span className="text-[10px] text-gray-600">
                        {new Date(publishedAt).toLocaleDateString("ru-RU")}
                      </span>
                    )}
                    {impactConfidence != null && (
                      <span className="text-[10px] text-gray-600">
                        Impact: {(impactConfidence * 100).toFixed(0)}%
                      </span>
                    )}
                    {anomalyScore != null && (
                      <span className="text-[10px] text-gray-600">
                        Anomaly: {(anomalyScore * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-gray-600 text-xs mt-1 transition-transform" style={{ transform: isExpanded ? "rotate(180deg)" : "none" }}>
                  \u25BC
                </div>
              </div>

              {isExpanded && (
                <div className="mt-3 pl-7 space-y-2 text-xs text-gray-400 bg-white/[0.02] rounded-xl p-3">
                  {reason && (
                    <p><span className="text-gray-500">Причина:</span> {reason}</p>
                  )}
                  {predictedReturn != null && (
                    <p><span className="text-gray-500">Predicted return:</span> <span className={`font-mono ${predictedReturn >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {predictedReturn >= 0 ? "+" : ""}{(predictedReturn * 100).toFixed(2)}%
                    </span></p>
                  )}
                  {sourceName && (
                    <p><span className="text-gray-500">Источник:</span> {sourceName}</p>
                  )}
                  {subcategory && (
                    <p><span className="text-gray-500">Подкатегория:</span> {subcategory}</p>
                  )}
                  <Link
                    href={`/instruments/${ticker}`}
                    className="inline-block mt-2 text-amber-400/80 hover:text-amber-400 transition"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Перейти к инструменту \u2192
                  </Link>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
