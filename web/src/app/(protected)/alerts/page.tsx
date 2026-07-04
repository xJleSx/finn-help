"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api-client";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AlertList } from "@/components/AlertList";
import { AlertAnalytics } from "@/components/AlertAnalytics";
import { AlertPreferences } from "@/components/AlertPreferences";
import { PriceTargetAlerts } from "@/components/PriceTargetAlerts";

export default function AlertsPage() {
  const [filter, setFilter] = useState<string>("all");

  const { data: alertsData, isLoading: alertsLoading, refetch: refetchAlerts } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.alerts.list(50),
    refetchInterval: 30_000,
  });

  const { data: analyticsData } = useQuery({
    queryKey: ["alert-analytics"],
    queryFn: () => api.alerts.analytics(30),
    refetchInterval: 120_000,
  });

  const { data: priceTargets } = useQuery({
    queryKey: ["price-targets"],
    queryFn: () => api.alerts.priceTargets(),
    refetchInterval: 60_000,
  });

  const { data: rebalanceAlerts } = useQuery({
    queryKey: ["rebalance-alerts"],
    queryFn: () => api.alerts.rebalance(),
    refetchInterval: 120_000,
  });

  const handleRefresh = async () => {
    try {
      await api.alerts.refresh();
      refetchAlerts();
    } catch { /* ignore */ }
  };

  const alerts = (alertsData?.alerts ?? []) as Array<Record<string, unknown>>;

  const filtered = filter === "all"
    ? alerts
    : alerts.filter((a) => (a.priority as string)?.toLowerCase() === filter);

  const tabs = [
    { value: "all", label: "Все", count: alerts.length },
    { value: "critical", label: "Критические", count: alerts.filter((a) => (a.priority as string)?.toLowerCase() === "critical").length },
    { value: "high", label: "Высокие", count: alerts.filter((a) => (a.priority as string)?.toLowerCase() === "high").length },
    { value: "medium", label: "Средние", count: alerts.filter((a) => (a.priority as string)?.toLowerCase() === "medium").length },
    { value: "low", label: "Низкие", count: alerts.filter((a) => (a.priority as string)?.toLowerCase() === "low").length },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-light text-white">Алерты</h1>
          <p className="text-sm text-gray-500 mt-1">Мониторинг и настройка оповещений</p>
        </div>
        <button
          onClick={handleRefresh}
          className="px-4 py-2 rounded-xl text-xs font-medium bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 transition"
        >
          Обновить
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className={`px-3 py-1.5 rounded-lg text-xs transition ${
              filter === tab.value
                ? "bg-amber-400/20 text-amber-400"
                : "bg-white/5 text-gray-500 hover:text-white"
            }`}
          >
            {tab.label} <span className="font-mono text-[10px] opacity-60">{tab.count}</span>
          </button>
        ))}
      </div>

      <ErrorBoundary>
        <AlertPreferences />
      </ErrorBoundary>

      <ErrorBoundary>
        {(priceTargets ?? []).length > 0 && (
          <PriceTargetAlerts targets={priceTargets ?? []} />
        )}
      </ErrorBoundary>

      <ErrorBoundary>
        {(rebalanceAlerts ?? []).length > 0 && (
          <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
            <h2 className="text-sm font-light text-white mb-3">Ребалансировка</h2>
            <div className="space-y-2">
              {rebalanceAlerts?.map((ra, i) => (
                <div key={i} className="flex items-center justify-between bg-white/[0.03] rounded-xl px-4 py-3 border border-white/5">
                  <div>
                    <span className="font-mono text-xs text-white">{ra.ticker}</span>
                    <span className="text-xs text-gray-500 ml-2">{ra.reason}</span>
                  </div>
                  <div className="text-xs font-mono">
                    <span className="text-gray-500">{ra.current_pct.toFixed(1)}%</span>
                    <span className="text-gray-600 mx-1">→</span>
                    <span className="text-amber-400">{ra.target_pct.toFixed(1)}%</span>
                    <span className={`ml-2 ${ra.deviation_pct > 0 ? "text-red-400" : "text-emerald-400"}`}>
                      ({ra.deviation_pct > 0 ? "+" : ""}{ra.deviation_pct.toFixed(1)}%)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </ErrorBoundary>

      <ErrorBoundary>
        {analyticsData && <AlertAnalytics data={analyticsData as Record<string, unknown>} />}
      </ErrorBoundary>

      <ErrorBoundary>
        <AlertList alerts={filtered} isLoading={alertsLoading} />
      </ErrorBoundary>
    </div>
  );
}
