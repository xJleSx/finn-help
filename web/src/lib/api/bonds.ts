import type { Bond } from "@/types/bond";
import type { BondAnalysis } from "@/types/bond-analysis";
import type { AIAnalysis } from "@/types/ai-analysis";
import type { BondMetrics } from "@/types/bond-metrics";
import type { BondDetails } from "@/types/bond-details";
import type { ChartData, ChartRange } from "@/types/chart";
import type { CouponPayment } from "@/types/coupon";
import type { CashFlowItemData, CashFlowSummaryData } from "@/types/cash-flow";
import { mapBondResponse } from "./bondMapper";

const USE_MOCK = true;

type BondResponse = Record<string, unknown>;

const MOCK_RESPONSES: BondResponse[] = [
  {
    id: "1", ticker: "SU26238RMFS4", isin: "RU000A1038V6", name: "ОФЗ 26238",
    issuer: "Минфин РФ", currentPrice: 987.5, purchasePrice: 956, nominal: 1000,
    couponValue: 37.4, couponYield: 15.4, yieldToMaturity: 16.7, duration: 4.8,
    rating: "AAA", couponFrequency: "SemiAnnual", nextCouponDate: "2026-09-14",
    maturityDate: "2031-05-15", quantity: 25, invested: 23900,
    currentValue: 24687.5, expectedRedemptionValue: 25000, unrealizedPnL: 787.5, aiScore: 94,
  },
  {
    id: "2", ticker: "GAZP2034", isin: "RU000A104F17", name: "Газпром 2034",
    issuer: "Газпром", currentPrice: 954, purchasePrice: 968, nominal: 1000,
    couponValue: 42, couponYield: 16.9, yieldToMaturity: 18.2, duration: 6.2,
    rating: "AA+", couponFrequency: "SemiAnnual", nextCouponDate: "2026-10-04",
    maturityDate: "2034-11-18", quantity: 12, invested: 11616,
    currentValue: 11448, expectedRedemptionValue: 12000, unrealizedPnL: -168, aiScore: 88,
  },
  {
    id: "3", ticker: "SBER2030", isin: "RU000A105K89", name: "Сбер 2030",
    issuer: "Сбербанк", currentPrice: 1002.3, purchasePrice: 995, nominal: 1000,
    couponValue: 40.5, couponYield: 16.1, yieldToMaturity: 16.0, duration: 3.5,
    rating: "AAA", couponFrequency: "Quarterly", nextCouponDate: "2026-08-01",
    maturityDate: "2030-04-22", quantity: 40, invested: 39800,
    currentValue: 40092, expectedRedemptionValue: 40000, unrealizedPnL: 292, aiScore: 91,
  },
  {
    id: "4", ticker: "VTBR2032", isin: "RU000A107G61", name: "ВТБ 2032",
    issuer: "Банк ВТБ", currentPrice: 971.2, purchasePrice: 980, nominal: 1000,
    couponValue: 43.8, couponYield: 17.3, yieldToMaturity: 18.5, duration: 5.1,
    rating: "AA-", couponFrequency: "Quarterly", nextCouponDate: "2026-09-20",
    maturityDate: "2032-08-03", quantity: 18, invested: 17640,
    currentValue: 17481.6, expectedRedemptionValue: 18000, unrealizedPnL: -158.4, aiScore: 85,
  },
  {
    id: "5", ticker: "LKOH2035", isin: "RU000A105Z02", name: "Лукойл 2035",
    issuer: "Лукойл", currentPrice: 938.7, purchasePrice: 915, nominal: 1000,
    couponValue: 46.0, couponYield: 18.9, yieldToMaturity: 20.1, duration: 7.0,
    rating: "A+", couponFrequency: "SemiAnnual", nextCouponDate: "2026-11-10",
    maturityDate: "2035-03-25", quantity: 8, invested: 7320,
    currentValue: 7509.6, expectedRedemptionValue: 8000, unrealizedPnL: 189.6, aiScore: 82,
  },
  {
    id: "6", ticker: "NLMK2029", isin: "RU000A102YK6", name: "НЛМК 2029",
    issuer: "НЛМК", currentPrice: 993.4, purchasePrice: 1005, nominal: 1000,
    couponValue: 38.2, couponYield: 15.2, yieldToMaturity: 15.5, duration: 2.8,
    rating: "A", couponFrequency: "SemiAnnual", nextCouponDate: "2026-07-25",
    maturityDate: "2029-09-12", quantity: 30, invested: 30150,
    currentValue: 29802, expectedRedemptionValue: 30000, unrealizedPnL: -348, aiScore: 79,
  },
];

function findBond(ticker: string): Bond | undefined {
  const raw = MOCK_RESPONSES.find((b) => b.ticker === ticker);
  return raw ? mapBondResponse(raw) : undefined;
}

export async function getBonds(): Promise<Bond[]> {
  if (USE_MOCK) {
    await delay(300);
    return MOCK_RESPONSES.map(mapBondResponse);
  }
  const res = await fetch("/api/proxy/instruments?type=bond");
  if (!res.ok) throw new Error("Failed to fetch bonds");
  return (await res.json()).map(mapBondResponse);
}

export async function getBondByTicker(ticker: string): Promise<Bond> {
  if (USE_MOCK) {
    await delay(200);
    const bond = findBond(ticker);
    if (!bond) throw new Error(`Bond ${ticker} not found`);
    return bond;
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}`);
  if (!res.ok) throw new Error("Failed to fetch bond");
  return mapBondResponse(await res.json());
}

export async function getBondDetails(ticker: string): Promise<BondDetails> {
  if (USE_MOCK) {
    await delay(150);
    const bond = findBond(ticker);
    if (!bond) throw new Error(`Bond ${ticker} not found`);
    return {
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
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/details`);
  if (!res.ok) throw new Error("Failed to fetch bond details");
  return res.json();
}

export async function getBondAnalysis(ticker: string): Promise<BondAnalysis> {
  if (USE_MOCK) {
    await delay(200);
    return {
      score: 94,
      verdict: "strong_buy",
      pros: [
        "Высокая надёжность — государственная ценная бумага",
        "Хорошая доходность относительно ключевой ставки",
        "Ликвидный инструмент с малым спредом",
      ],
      cons: [],
      risks: [
        "Изменение ключевой ставки ЦБ",
        "Инфляционные риски",
        "Валютные риски при ослаблении рубля",
      ],
      allocation: 18,
      updatedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    };
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/analysis`);
  if (!res.ok) throw new Error("Failed to fetch analysis");
  return res.json();
}

export async function getAIAnalysis(ticker: string): Promise<AIAnalysis> {
  if (USE_MOCK) {
    await delay(250);
    return {
      summary: "ОФЗ 26238 — государственная облигация с фиксированным купоном. Эмитент — Минфин РФ. Инструмент подходит для консервативных инвесторов.",
      strengths: [
        "Высокая кредитоспособность — государственная гарантия",
        "Хорошая ликвидность на вторичном рынке",
        "Доходность выше среднерыночной по ОФЗ",
      ],
      weaknesses: [
        "Низкая доходность относительно корпоративных облигаций",
        "Чувствительность к изменению ключевой ставки ЦБ",
      ],
      risks: [
        "Возможное снижение цены при повышении ключевой ставки",
        "Инфляционные риски при длительном горизонте",
      ],
      recommendation: "Покупать",
      investmentHorizon: "3–5 лет",
      confidence: 89,
    };
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/ai-analysis`);
  if (!res.ok) throw new Error("Failed to fetch AI analysis");
  return res.json();
}

export async function getBondMetrics(ticker: string): Promise<BondMetrics> {
  if (USE_MOCK) {
    await delay(150);
    const bond = findBond(ticker);
    if (!bond) throw new Error(`Bond ${ticker} not found`);
    return {
      yieldToMaturity: bond.yieldToMaturity,
      currentYield: bond.couponYield,
      duration: bond.duration,
      modifiedDuration: bond.duration * 0.95,
      coupon: bond.couponValue,
      accruedInterest: (bond.couponValue / 180) * 45,
      purchasePrice: bond.purchasePrice,
      marketPrice: bond.currentPrice,
      profit: bond.unrealizedPnL,
      fairValue: bond.currentPrice * 1.025,
    };
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.json();
}

export async function getBondPriceHistory(ticker: string, range: ChartRange = "1M"): Promise<ChartData> {
  if (USE_MOCK) {
    await delay(300);
    const bond = findBond(ticker);
    const days = range === "1D" ? 1 : range === "5D" ? 5 : range === "1M" ? 30 : range === "3M" ? 90 : range === "6M" ? 180 : range === "1Y" ? 365 : range === "3Y" ? 1095 : 1825;
    const price = Array.from({ length: days }, (_, i) => {
      const d = new Date(Date.now() - (days - 1 - i) * 86_400_000);
      const base = bond?.currentPrice ?? 1000;
      const noise = Math.sin(i / 10) * 15 + (Math.random() - 0.5) * 8;
      return { time: d.toISOString().slice(0, 10), value: +(base - 30 + noise).toFixed(2) };
    });
    const volume = price.map((p) => ({
      time: p.time,
      value: Math.round(500_000 + Math.random() * 3_000_000),
    }));
    return { price, volume };
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/price-history?range=${range}`);
  if (!res.ok) throw new Error("Failed to fetch price history");
  return res.json();
}

export async function getBondCoupons(ticker: string): Promise<CouponPayment[]> {
  if (USE_MOCK) {
    await delay(200);
    const bond = findBond(ticker);
    if (!bond) throw new Error(`Bond ${ticker} not found`);
    return Array.from({ length: 12 }, (_, i) => {
      const d = new Date(bond.maturityDate);
      d.setMonth(d.getMonth() - i * 6);
      return {
        id: `${ticker}-cpn-${i}`,
        date: d.toISOString(),
        amount: bond.couponValue,
        status: i < 4 ? "paid" as const : i < 7 ? "pending" as const : "forecast" as const,
      };
    });
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/coupons`);
  if (!res.ok) throw new Error("Failed to fetch coupons");
  return res.json();
}

export async function getBondCashFlow(ticker: string): Promise<{ items: CashFlowItemData[]; summary: CashFlowSummaryData }> {
  if (USE_MOCK) {
    await delay(200);
    const bond = findBond(ticker);
    if (!bond) throw new Error(`Bond ${ticker} not found`);
    const items: CashFlowItemData[] = [
      ...Array.from({ length: 24 }, (_, i) => {
        const d = new Date(bond.nextCouponDate);
        d.setMonth(d.getMonth() + i * 6);
        return {
          id: `${ticker}-cf-cpn-${i}`,
          date: d.toISOString(),
          amount: bond.couponValue,
          type: "coupon" as const,
          status: i < 3 ? "paid" as const : i < 6 ? "expected" as const : "forecast" as const,
        };
      }),
      {
        id: `${ticker}-cf-red`,
        date: bond.maturityDate,
        amount: bond.nominal + bond.couponValue,
        type: "redemption" as const,
        status: "forecast" as const,
      },
    ];
    const summary: CashFlowSummaryData = {
      totalPayments: items.length,
      remainingCoupons: items.filter((i) => i.type === "coupon" && i.status !== "paid").length,
      totalCashFlow: items.reduce((sum, i) => sum + i.amount, 0),
      averageCoupon: bond.couponValue,
      maturityDate: bond.maturityDate,
    };
    return { items, summary };
  }
  const res = await fetch(`/api/proxy/instruments/${ticker}/cash-flow`);
  if (!res.ok) throw new Error("Failed to fetch cash flow");
  return res.json();
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
