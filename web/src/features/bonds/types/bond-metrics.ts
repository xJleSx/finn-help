export type Trend = "positive" | "neutral" | "negative";

export interface BondMetrics {
  yieldToMaturity: number;
  currentYield: number;
  duration: number;
  modifiedDuration: number;
  coupon: number;
  accruedInterest: number;
  purchasePrice: number;
  marketPrice: number;
  profit: number;
  fairValue: number;
}
