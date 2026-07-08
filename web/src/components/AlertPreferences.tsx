"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api-client";

const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;

export function AlertPreferences() {
  const queryClient = useQueryClient();

  const { data: prefs, isLoading } = useQuery({
    queryKey: ["alert-preferences"],
    queryFn: () => api.alerts.preferences.get(),
    refetchInterval: 120_000,
  });

  const [newTicker, setNewTicker] = useState("");
  const [severity, setSeverity] = useState("LOW");
  const [qhStart, setQhStart] = useState("");
  const [qhEnd, setQhEnd] = useState("");

  const updateMutation = useMutation({
    mutationFn: (body: { min_severity?: string; quiet_hours_start?: string | null; quiet_hours_end?: string | null }) =>
      api.alerts.preferences.update(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-preferences"] }),
  });

  const muteMutation = useMutation({
    mutationFn: (ticker: string) => api.alerts.preferences.mute(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-preferences"] });
      setNewTicker("");
    },
  });

  const unmuteMutation = useMutation({
    mutationFn: (ticker: string) => api.alerts.preferences.unmute(ticker),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-preferences"] }),
  });

  if (isLoading) {
    return (
      <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
        <h2 className="text-sm font-light text-white mb-4">Настройки алертов</h2>
        <p className="text-xs text-gray-500">Загрузка...</p>
      </section>
    );
  }

  if (!prefs) return null;

  const hasQuietHours = !!prefs.quiet_hours_start && !!prefs.quiet_hours_end;

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4">Настройки алертов</h2>

      <div className="space-y-4">
        <div>
          <label className="text-xs text-gray-500 block mb-1.5">Минимальная важность</label>
          <div className="flex flex-wrap gap-1.5">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setSeverity(s);
                  updateMutation.mutate({ min_severity: s });
                }}
                className={`px-3 py-1.5 rounded-lg text-xs transition ${
                  (prefs.min_severity === s)
                    ? "bg-amber-400/20 text-amber-400 border border-amber-400/30"
                    : "bg-white/5 text-gray-500 hover:text-white border border-transparent"
                }`}
              >
                {s === "LOW" ? "Низкая" : s === "MEDIUM" ? "Средняя" : s === "HIGH" ? "Высокая" : "Критическая"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1.5">Заглушенные тикеры</label>
          {prefs.muted_tickers.length === 0 ? (
            <p className="text-xs text-gray-500">Нет заглушенных тикеров</p>
          ) : (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {prefs.muted_tickers.map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-xs font-mono text-gray-300"
                >
                  {t}
                  <button
                    onClick={() => unmuteMutation.mutate(t)}
                    className="text-red-400 hover:text-red-300 transition"
                    aria-label={`Убрать заглушение для ${t}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              value={newTicker}
              onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
              placeholder="SBER"
              className="flex-1 bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/30 font-mono"
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTicker.trim()) {
                  muteMutation.mutate(newTicker.trim());
                }
              }}
            />
            <button
              onClick={() => {
                if (newTicker.trim()) muteMutation.mutate(newTicker.trim());
              }}
              disabled={!newTicker.trim() || muteMutation.isPending}
              className="px-3 py-1.5 rounded-xl text-xs font-medium bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 transition disabled:opacity-40"
            >
              Заглушить
            </button>
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1.5">Тихие часы</label>
          <div className="flex items-center gap-2">
            <input
              type="time"
              value={prefs.quiet_hours_start ?? qhStart}
              onChange={(e) => setQhStart(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-400/30"
            />
            <span className="text-gray-600 text-xs">—</span>
            <input
              type="time"
              value={prefs.quiet_hours_end ?? qhEnd}
              onChange={(e) => setQhEnd(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-400/30"
            />
            <button
              onClick={() => {
                const valQhStart = prefs.quiet_hours_start ?? qhStart;
                const valQhEnd = prefs.quiet_hours_end ?? qhEnd;
                updateMutation.mutate({
                  quiet_hours_start: valQhStart || null,
                  quiet_hours_end: valQhEnd || null,
                });
              }}
              disabled={updateMutation.isPending}
              className="px-3 py-1.5 rounded-xl text-xs font-medium bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 transition disabled:opacity-40"
            >
              {hasQuietHours ? "Обновить" : "Установить"}
            </button>
            {hasQuietHours && (
              <button
                onClick={() => updateMutation.mutate({ quiet_hours_start: null, quiet_hours_end: null })}
                className="px-3 py-1.5 rounded-xl text-xs text-red-400 hover:text-red-300 transition"
              >
                Сбросить
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
