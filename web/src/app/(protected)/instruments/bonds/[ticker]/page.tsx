"use client";

import { use } from "react";
import { useBond } from "@/hooks/bonds/useBond";
import { useBondAnalysis, useAIAnalysis, useBondMetrics } from "@/hooks/bonds/useBondAnalysis";
import { useBondCoupons } from "@/hooks/bonds/useBondCoupons";
import { useBondCashFlow } from "@/hooks/bonds/useBondCashFlow";
import { useBondPriceHistory } from "@/hooks/bonds/useBondPriceHistory";

import { AISummaryCard } from "@/components/bonds/details/AISummaryCard";
import { BondOverviewCard } from "@/components/bonds/details/BondOverviewCard";
import { FinancialMetricsCard } from "@/components/bonds/details/FinancialMetricsCard";
import { PriceChartCard } from "@/components/bonds/details/PriceChartCard";
import { CouponHistoryCard } from "@/components/bonds/details/CouponHistoryCard";
import { CashFlowCard } from "@/components/bonds/details/CashFlowCard";
import { AIAnalysisCard } from "@/components/bonds/details/AIAnalysisCard";
import { CardErrorBoundary } from "@/components/bonds/details/ErrorBoundary";

import AISummarySkeleton from "@/components/bonds/details/skeleton/AISummarySkeleton";
import MetricsSkeleton from "@/components/bonds/details/skeleton/MetricsSkeleton";
import ChartSkeleton from "@/components/bonds/details/skeleton/ChartSkeleton";
import CashFlowSkeleton from "@/components/bonds/details/skeleton/CashFlowSkeleton";
import CouponSkeleton from "@/components/bonds/details/skeleton/CouponSkeleton";
import AIAnalysisSkeleton from "@/components/bonds/details/skeleton/AIAnalysisSkeleton";
import OverviewSkeleton from "@/components/bonds/details/skeleton/OverviewSkeleton";

import { Building2 } from "lucide-react";
import type { BondDetails } from "@/types/bond-details";

export default function BondDetailPage({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);

  const { data: bond, isLoading: bondLoading } = useBond(ticker);
  const { data: analysis, isLoading: analysisLoading } = useBondAnalysis(ticker);
  const { data: aiAnalysis, isLoading: aiLoading } = useAIAnalysis(ticker);
  const { data: metrics, isLoading: metricsLoading } = useBondMetrics(ticker);
  const { data: coupons, isLoading: couponsLoading } = useBondCoupons(ticker);
  const { data: cashFlow, isLoading: cashFlowLoading } = useBondCashFlow(ticker);
  const { data: priceHistory, isLoading: chartLoading } = useBondPriceHistory(ticker);

  if (bondLoading) return <LoadingState />;
  if (!bond) return <NotFound ticker={ticker} />;

  const details: BondDetails = {
    issuer: bond.issuer,
    isin: bond.isin,
    ticker: bond.ticker,
    currency: "RUB",
    nominal: bond.nominal,
    couponRate: bond.couponYield,
    issueDate: "2021-06-15",
    maturityDate: bond.maturityDate,
    offerDate: null,
    amortization: false,
  };

  return (
    <main className="space-y-8 p-8">
      <Header name={bond.name} issuer={bond.issuer} isin={bond.isin} />

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <CardErrorBoundary name="AI Summary">
          {analysisLoading ? <AISummarySkeleton /> : analysis ? (
            <AISummaryCard name={bond.name} ticker={bond.ticker} analysis={analysis} />
          ) : null}
        </CardErrorBoundary>

        <div className="space-y-6">
          <CardErrorBoundary name="Основная информация">
            <BondOverviewCard details={details} />
          </CardErrorBoundary>

          <CardErrorBoundary name="Финансовые показатели">
            {metricsLoading ? <MetricsSkeleton /> : metrics ? (
              <FinancialMetricsCard metrics={metrics} />
            ) : null}
          </CardErrorBoundary>
        </div>
      </div>

      <CardErrorBoundary name="График цены">
        {chartLoading ? <ChartSkeleton /> : priceHistory ? (
          <PriceChartCard data={priceHistory} currentPrice={bond.currentPrice} volume={5_000_000} />
        ) : null}
      </CardErrorBoundary>

      <CardErrorBoundary name="История купонных выплат">
        {couponsLoading ? <CouponSkeleton /> : coupons ? (
          <CouponHistoryCard payments={coupons} />
        ) : null}
      </CardErrorBoundary>

      <div className="grid gap-6 lg:grid-cols-2">
        <CardErrorBoundary name="Cash Flow">
          {cashFlowLoading ? <CashFlowSkeleton /> : cashFlow ? (
            <CashFlowCard items={cashFlow.items} summary={cashFlow.summary} />
          ) : null}
        </CardErrorBoundary>

        <CardErrorBoundary name="AI Анализ">
          {aiLoading ? <AIAnalysisSkeleton /> : aiAnalysis ? (
            <AIAnalysisCard analysis={aiAnalysis} />
          ) : null}
        </CardErrorBoundary>
      </div>
    </main>
  );
}

function Header({ name, issuer, isin }: { name: string; issuer: string; isin: string }) {
  return (
    <div className="flex items-center gap-4">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
        <Building2 className="h-7 w-7 text-primary" />
      </div>
      <div>
        <h1 className="text-3xl font-bold text-foreground">{name}</h1>
        <p className="text-sm text-muted-foreground">{issuer} · {isin}</p>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-8 p-8">
      <div className="flex items-center gap-4 animate-pulse">
        <div className="h-14 w-14 rounded-2xl bg-muted" />
        <div className="space-y-2">
          <div className="h-7 w-48 rounded bg-muted" />
          <div className="h-4 w-64 rounded bg-muted" />
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <AISummarySkeleton />
        <div className="space-y-6">
          <OverviewSkeleton />
          <MetricsSkeleton />
        </div>
      </div>
      <ChartSkeleton />
    </div>
  );
}

function NotFound({ ticker }: { ticker: string }) {
  return (
    <div className="flex h-96 items-center justify-center">
      <div className="text-center">
        <div className="text-4xl">🔍</div>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Облигация не найдена</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Облигация с тикером <span className="font-mono">{ticker}</span> не найдена
        </p>
      </div>
    </div>
  );
}
