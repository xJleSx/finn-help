"use client";

import { useMemo } from "react";
import { PortfolioSummary, PortfolioTable, PortfolioAllocation, PortfolioPerformance, PortfolioCashFlow, PortfolioAI } from "@/features/portfolio/components";
import { usePortfolioBonds } from "@/features/portfolio/hooks/usePortfolio";
import type { CashFlowEvent } from "@/features/portfolio/components/PortfolioCashFlow";
import type { PortfolioAIProps } from "@/features/portfolio/components/PortfolioAI";
import { Building2 } from "lucide-react";

export default function PortfolioBondsPage() {
  const { data, isLoading, error } = usePortfolioBonds();

  const performance = useMemo(() => {
    if (!data?.positions?.length) return [];
    const sorted = [...data.positions].sort((a, b) => a.ticker.localeCompare(b.ticker));
    return sorted.slice(0, 10).map((p, i) => ({
      time: p.ticker,
      value: p.totalValue,
    }));
  }, [data]);

  const cashFlow: CashFlowEvent[] = useMemo(() => {
    if (!data?.positions?.length) return [];
    const now = new Date();
    return data.positions.slice(0, 12).map((p, i) => {
      const m = new Date(now.getFullYear(), now.getMonth() - i, 1);
      return {
        month: m.toLocaleString("ru", { month: "short", year: "numeric" }),
        amount: Math.round(p.couponYield * p.totalValue / 100 / 12),
      };
    }).reverse();
  }, [data]);

  const aiProps: PortfolioAIProps = useMemo(() => {
    if (!data) return { risk: "—", diversification: 0, avgRating: "—", recommendation: "Загрузка...", expectedReturn: 0 };
    const ratings = data.positions.map(p => p.rating);
    const avgRating = ratings.filter(r => r && r !== "NR").sort()[Math.floor(ratings.filter(r => r && r !== "NR").length / 2)] || "NR";
    return {
      risk: data.summary.avgYtm > 15 ? "Выше среднего" : data.summary.avgYtm > 10 ? "Средний" : "Низкий",
      diversification: Math.min(100, data.positions.length * 15),
      avgRating,
      recommendation: data.summary.avgYtm > 12 ? "Хороший момент для фиксации доходности" : data.summary.avgYtm > 8 ? "Держать" : "Рассмотреть замену",
      expectedReturn: data.summary.avgYtm,
    };
  }, [data]);

  if (isLoading) {
    return (
      <main className="space-y-8 p-8">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <Building2 className="h-7 w-7 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-foreground">Портфель облигаций</h1>
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          </div>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="space-y-8 p-8">
        <div className="flex items-center gap-4">
          <Building2 className="h-7 w-7 text-primary" />
          <h1 className="text-3xl font-bold text-foreground">Ошибка загрузки портфеля</h1>
        </div>
        <p className="text-muted-foreground">{(error as Error).message}</p>
      </main>
    );
  }

  return (
    <main className="space-y-8 p-8">
      <div className="flex items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
          <Building2 className="h-7 w-7 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-foreground">Портфель облигаций</h1>
          <p className="text-sm text-muted-foreground">
            {data?.positions?.length || 0} позиций · {data?.summary?.totalValue?.toLocaleString("ru", { style: "currency", currency: "RUB", minimumFractionDigits: 0 })}
          </p>
        </div>
      </div>

      {data?.summary && <PortfolioSummary summary={data.summary} />}

      {data?.positions && (
        <PortfolioTable
          positions={data.positions}
          onRowClick={(position) => {
            window.location.href = `/instruments/bonds/${position.ticker}`;
          }}
        />
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <PortfolioAllocation allocation={{ recommended: data?.allocation?.recommended?.length ? 18 : 18, actual: data?.allocation?.actual?.length ? Math.round(data.allocation.actual[0]?.value || 0) : 0 }} />
        <PortfolioPerformance data={performance} totalReturn={data?.summary?.totalReturn || 0} currentValue={data?.summary?.totalValue || 0} />
      </div>

      {data?.scenarioB && (
        <div className="rounded-xl border bg-card p-6">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Сценарий B {data.scenarioB.scenarioBActive ? "🔴 Активен" : "🟢 Не активен"}
          </h3>
          <p className="mb-3 text-sm text-muted-foreground">{data.scenarioB.triggerReason}</p>
          {data.scenarioB.sellRecommendations.length > 0 && (
            <div className="mb-3">
              <p className="mb-1 text-xs font-semibold text-red-500">Рекомендации к продаже:</p>
              <ul className="space-y-1 text-sm text-muted-foreground">
                {data.scenarioB.sellRecommendations.map((s, i) => (
                  <li key={i}>• {s.ticker}: {s.reason}</li>
                ))}
              </ul>
            </div>
          )}
          {data.scenarioB.buyRecommendations.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold text-emerald-500">Рекомендации к покупке:</p>
              <ul className="space-y-1 text-sm text-muted-foreground">
                {data.scenarioB.buyRecommendations.map((b, i) => (
                  <li key={i}>• {b.ticker} ({b.suggestedPct}%) — {b.reason}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {data?.rebalancing && data.rebalancing.triggerCount > 0 && (
        <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/5 p-6">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Триггеры ребалансировки ({data.rebalancing.triggerCount})
          </h3>
          <ul className="space-y-2 text-sm">
            {data.rebalancing.activeTriggers.map((t, i) => (
              <li key={i} className={`flex gap-2 ${t.severity === "high" ? "text-red-500" : t.severity === "medium" ? "text-yellow-500" : "text-muted-foreground"}`}>
                <span>•</span>
                <span>{t.message}</span>
              </li>
            ))}
          </ul>
          {data.rebalancing.recommendations.length > 0 && (
            <div className="mt-3 border-t border-border/50 pt-3">
              <p className="mb-1 text-xs font-semibold">Рекомендации:</p>
              <ul className="space-y-1 text-sm text-muted-foreground">
                {data.rebalancing.recommendations.map((r, i) => (
                  <li key={i}>• {r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {data?.macroScenario && (
        <div className="rounded-xl border bg-card p-6">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Макро-сценарий
          </h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Сценарий</span><span className="font-semibold">{data.macroScenario.selectedScenario}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Оценка</span><span className="font-semibold">{data.macroScenario.score}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Ключевая ставка</span><span className="font-semibold">{(data.macroScenario.keyRate * 100).toFixed(0)}%</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Инфляция</span><span className="font-semibold">{(data.macroScenario.inflation * 100).toFixed(1)}%</span></div>
            <p className="mt-2 text-xs text-muted-foreground">{data.macroScenario.details}</p>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <PortfolioCashFlow events={cashFlow} />
        <PortfolioAI {...aiProps} />
      </div>
    </main>
  );
}
