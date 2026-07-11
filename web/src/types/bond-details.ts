export interface BondDetails {
  issuer: string;
  isin: string;
  ticker: string;
  currency: string;
  nominal: number;
  couponRate: number;
  issueDate: string;
  maturityDate: string;
  offerDate: string | null;
  amortization: boolean;
}

export interface FinancialMetrics {
  yieldToMaturity: number;
  currentYield: number;
  modifiedDuration: number;
  macaulayDuration: number;
  accruedInterest: number;
  couponFrequency: string;
  effectiveYield: number;
  avgPurchasePrice: number;
  currentProfit: number;
}
