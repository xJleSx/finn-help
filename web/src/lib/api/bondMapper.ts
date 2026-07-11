import type { Bond, BondRating, CouponFrequency } from "@/types/bond";

type BondResponse = Record<string, unknown>;

const VALID_RATINGS = new Set<string>([
  "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
  "BBB+", "BBB", "BBB-", "BB+", "BB", "NR",
]);

const VALID_FREQUENCIES = new Set<string>([
  "Monthly", "Quarterly", "SemiAnnual", "Annual",
]);

function toRating(raw: unknown): BondRating {
  const s = String(raw ?? "NR");
  return VALID_RATINGS.has(s) ? (s as BondRating) : "NR";
}

function toFrequency(raw: unknown): CouponFrequency {
  const s = String(raw ?? "SemiAnnual");
  return VALID_FREQUENCIES.has(s) ? (s as CouponFrequency) : "SemiAnnual";
}

function toNumber(raw: unknown, fallback: number): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

export function mapBondResponse(raw: BondResponse): Bond {
  return {
    id: String(raw.id ?? ""),
    ticker: String(raw.ticker ?? ""),
    isin: String(raw.isin ?? ""),
    name: String(raw.name ?? ""),
    issuer: String(raw.issuer ?? ""),
    currentPrice: toNumber(raw.currentPrice, 0),
    purchasePrice: toNumber(raw.purchasePrice, 0),
    nominal: toNumber(raw.nominal, 1000),
    couponValue: toNumber(raw.couponValue, 0),
    couponYield: toNumber(raw.couponYield, 0),
    yieldToMaturity: toNumber(raw.yieldToMaturity, 0),
    duration: toNumber(raw.duration, 0),
    rating: toRating(raw.rating),
    couponFrequency: toFrequency(raw.couponFrequency),
    nextCouponDate: String(raw.nextCouponDate ?? ""),
    maturityDate: String(raw.maturityDate ?? ""),
    quantity: toNumber(raw.quantity, 0),
    invested: toNumber(raw.invested, 0),
    currentValue: toNumber(raw.currentValue, 0),
    expectedRedemptionValue: toNumber(raw.expectedRedemptionValue, 0),
    unrealizedPnL: toNumber(raw.unrealizedPnL, 0),
    aiScore: toNumber(raw.aiScore, 50),
  };
}
