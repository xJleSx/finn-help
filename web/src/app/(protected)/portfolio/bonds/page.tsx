"use client";

import { PortfolioSummary, PortfolioTable, PortfolioAllocation, PortfolioPerformance, PortfolioCashFlow, PortfolioAI } from "@/components/portfolio/bonds";
import type { BondPosition } from "@/types/portfolio/bond-position";
import type { BondPortfolioSummary } from "@/types/portfolio/bond-summary";
import type { BondAllocation } from "@/types/portfolio/bond-allocation";
import type { CashFlowEvent } from "@/components/portfolio/bonds/PortfolioCashFlow";
import type { PortfolioAIProps } from "@/components/portfolio/bonds/PortfolioAI";
import { Building2 } from "lucide-react";

const MOCK_POSITIONS: BondPosition[] = [
  { id: "1", ticker: "SU26238RMFS4", isin: "RU000A1038V6", name: "ОФЗ 26238", issuer: "Минфин РФ", quantity: 25, avgPrice: 956, currentPrice: 987.5, totalValue: 24687.5, totalInvested: 23900, profit: 787.5, profitPercent: 3.29, ytm: 16.7, aiScore: 94, rating: "AAA", allocation: 18.5 },
  { id: "2", ticker: "GAZP2034", isin: "RU000A104F17", name: "Газпром 2034", issuer: "Газпром", quantity: 12, avgPrice: 968, currentPrice: 954, totalValue: 11448, totalInvested: 11616, profit: -168, profitPercent: -1.45, ytm: 18.2, aiScore: 88, rating: "AA+", allocation: 8.6 },
  { id: "3", ticker: "SBER2030", isin: "RU000A105K89", name: "Сбер 2030", issuer: "Сбербанк", quantity: 40, avgPrice: 995, currentPrice: 1002.3, totalValue: 40092, totalInvested: 39800, profit: 292, profitPercent: 0.73, ytm: 16.0, aiScore: 91, rating: "AAA", allocation: 30.1 },
  { id: "4", ticker: "VTBR2032", isin: "RU000A107G61", name: "ВТБ 2032", issuer: "Банк ВТБ", quantity: 18, avgPrice: 980, currentPrice: 971.2, totalValue: 17481.6, totalInvested: 17640, profit: -158.4, profitPercent: -0.9, ytm: 18.5, aiScore: 85, rating: "AA-", allocation: 13.1 },
  { id: "5", ticker: "LKOH2035", isin: "RU000A105Z02", name: "Лукойл 2035", issuer: "Лукойл", quantity: 8, avgPrice: 915, currentPrice: 938.7, totalValue: 7509.6, totalInvested: 7320, profit: 189.6, profitPercent: 2.59, ytm: 20.1, aiScore: 82, rating: "A+", allocation: 5.6 },
  { id: "6", ticker: "NLMK2029", isin: "RU000A102YK6", name: "НЛМК 2029", issuer: "НЛМК", quantity: 30, avgPrice: 1005, currentPrice: 993.4, totalValue: 29802, totalInvested: 30150, profit: -348, profitPercent: -1.15, ytm: 15.5, aiScore: 79, rating: "A", allocation: 22.4 },
  { id: "7", ticker: "ROSN2033", isin: "RU000A1039P4", name: "Роснефть 2033", issuer: "Роснефть", quantity: 3, avgPrice: 945, currentPrice: 962, totalValue: 2886, totalInvested: 2835, profit: 51, profitPercent: 1.8, ytm: 17.8, aiScore: 86, rating: "AA", allocation: 2.2 },
];

const MOCK_SUMMARY: BondPortfolioSummary = {
  totalValue: MOCK_POSITIONS.reduce((s, p) => s + p.totalValue, 0),
  totalProfit: MOCK_POSITIONS.reduce((s, p) => s + p.profit, 0),
  totalReturn: ((MOCK_POSITIONS.reduce((s, p) => s + p.totalValue, 0) - MOCK_POSITIONS.reduce((s, p) => s + p.totalInvested, 0)) / MOCK_POSITIONS.reduce((s, p) => s + p.totalInvested, 0)) * 100,
  avgYtm: MOCK_POSITIONS.reduce((s, p) => s + p.ytm, 0) / MOCK_POSITIONS.length,
  avgAiScore: Math.round(MOCK_POSITIONS.reduce((s, p) => s + p.aiScore, 0) / MOCK_POSITIONS.length),
};

const MOCK_ALLOCATION: BondAllocation = {
  recommended: 18,
  actual: 11,
};

const MOCK_PERFORMANCE = Array.from({ length: 180 }, (_, i) => {
  const d = new Date(Date.now() - (179 - i) * 86_400_000);
  return {
    time: d.toISOString().slice(0, 10),
    value: +(1_700_000 + Math.sin(i / 15) * 80_000 + (Math.random() - 0.5) * 40_000).toFixed(2),
  };
});

const MOCK_CASH_FLOW: CashFlowEvent[] = [
  { month: "Янв 2026", amount: 34_200 },
  { month: "Фев 2026", amount: 12_400 },
  { month: "Мар 2026", amount: 28_900 },
  { month: "Апр 2026", amount: 45_100 },
  { month: "Май 2026", amount: 18_600 },
  { month: "Июн 2026", amount: 52_300 },
  { month: "Июл 2026", amount: 24_800 },
  { month: "Авг 2026", amount: 36_700 },
  { month: "Сен 2026", amount: 41_200 },
  { month: "Окт 2026", amount: 19_500 },
  { month: "Ноя 2026", amount: 33_600 },
  { month: "Дек 2026", amount: 47_900 },
];

const MOCK_AI: PortfolioAIProps = {
  risk: "Низкий",
  diversification: 82,
  avgRating: "AA+",
  recommendation: "Добавить корпоративные облигации для повышения доходности",
  expectedReturn: 9.6,
};

export default function PortfolioBondsPage() {
  return (
    <main className="space-y-8 p-8">
      <div className="flex items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
          <Building2 className="h-7 w-7 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-foreground">Портфель облигаций</h1>
          <p className="text-sm text-muted-foreground">Управление портфелем и аналитика</p>
        </div>
      </div>

      <PortfolioSummary summary={MOCK_SUMMARY} />

      <PortfolioTable
        positions={MOCK_POSITIONS}
        onRowClick={(position) => {
          window.location.href = `/instruments/bonds/${position.ticker}`;
        }}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <PortfolioAllocation allocation={MOCK_ALLOCATION} />
        <PortfolioPerformance data={MOCK_PERFORMANCE} totalReturn={7.74} currentValue={MOCK_SUMMARY.totalValue} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <PortfolioCashFlow events={MOCK_CASH_FLOW} />
        <PortfolioAI {...MOCK_AI} />
      </div>
    </main>
  );
}
