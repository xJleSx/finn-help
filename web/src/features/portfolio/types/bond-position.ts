export interface BondPosition {
  id: string;
  ticker: string;
  isin: string;
  name: string;
  issuer: string;
  quantity: number;
  avgPrice: number;
  currentPrice: number;
  totalValue: number;
  totalInvested: number;
  profit: number;
  profitPercent: number;
  ytm: number;
  couponYield: number;
  duration: number;
  rating: string;
  maturityDate: string;
  aiScore: number;
  allocation: number;
  targetAllocation?: number;
}
