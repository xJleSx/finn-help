export type BondRating =
  | "AAA"
  | "AA+"
  | "AA"
  | "AA-"
  | "A+"
  | "A"
  | "A-"
  | "BBB+"
  | "BBB"
  | "BBB-"
  | "BB+"
  | "BB"
  | "NR";

export type CouponFrequency =
  | "Monthly"
  | "Quarterly"
  | "SemiAnnual"
  | "Annual";

export interface Bond {
  id: string;
  ticker: string;
  isin: string;
  name: string;
  issuer: string;
  currentPrice: number;
  purchasePrice: number;
  nominal: number;
  couponValue: number;
  couponYield: number;
  yieldToMaturity: number;
  duration: number;
  rating: BondRating;
  couponFrequency: CouponFrequency;
  nextCouponDate: string;
  maturityDate: string;
  quantity: number;
  invested: number;
  currentValue: number;
  expectedRedemptionValue: number;
  unrealizedPnL: number;
  aiScore: number;
}
