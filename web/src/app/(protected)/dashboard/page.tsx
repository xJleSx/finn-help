"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { PortfolioOverview } from "@/components/PortfolioOverview";
import { PositionsTable } from "@/components/PositionsTable";
import { RiskMetricsCard } from "@/components/RiskMetricsCard";
import { PerformanceChart } from "@/components/PerformanceChart";
import MacroPanel from "@/components/MacroPanel";
import NewsPanel from "@/components/NewsPanel";
import GeoRiskPanel from "@/components/GeoRiskPanel";

export default function DashboardPage() {
  const { data: positions, isLoading: posLoading } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.portfolio.list(),
    refetchInterval: 30_000,
  });

  const { data: riskData, isLoading: riskLoading } = useQuery({
    queryKey: ["risk-portfolio"],
    queryFn: () => api.analysis.riskPortfolio(),
    refetchInterval: 60_000,
  });

  const { data: macroData } = useQuery({
    queryKey: ["macro"],
    queryFn: () => api.macro.latest().catch(() => null),
    refetchInterval: 300_000,
  });

  const { data: newsData } = useQuery({
    queryKey: ["news"],
    queryFn: () => api.news.list(5),
    refetchInterval: 120_000,
  });

  const { data: geoData } = useQuery({
    queryKey: ["geo"],
    queryFn: () => api.geo.history(14),
    refetchInterval: 300_000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-light text-white">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Обзор портфеля, риск-метрики и рынок</p>
      </div>

      <ErrorBoundary>
        <PortfolioOverview positions={positions ?? []} isLoading={posLoading} />
      </ErrorBoundary>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <ErrorBoundary>
            <PerformanceChart positions={positions ?? []} />
          </ErrorBoundary>

          <ErrorBoundary>
            <RiskMetricsCard data={riskData as Record<string, unknown> | null} isLoading={riskLoading} />
          </ErrorBoundary>

          <ErrorBoundary>
            <PositionsTable positions={positions ?? []} isLoading={posLoading} />
          </ErrorBoundary>
        </div>

        <aside className="space-y-5">
          <ErrorBoundary>
            {macroData && <MacroPanel data={macroData as unknown as { brent: number | null; usd_rate: number | null; imoex: number | null; key_rate: number | null; cpi: number | null; ofz_10y: number | null; m2: number | null }} />}
          </ErrorBoundary>
          <ErrorBoundary>
            {newsData && <NewsPanel news={newsData} />}
          </ErrorBoundary>
          <ErrorBoundary>
            {geoData && <GeoRiskPanel geoHistory={geoData} />}
          </ErrorBoundary>
        </aside>
      </div>
    </div>
  );
}
