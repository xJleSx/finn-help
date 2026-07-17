const API_BASE = "/api/proxy/portfolio";

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
}

export interface PortfolioSummary {
  totalValue: number;
  totalProfit: number;
  totalReturn: number;
  avgYtm: number;
  avgAiScore: number;
}

export interface AllocationItem {
  label: string;
  value: number;
}

export interface PortfolioResponse {
  positions: BondPosition[];
  summary: PortfolioSummary;
  allocation: {
    recommended: AllocationItem[];
    actual: AllocationItem[];
  };
}

export async function getPortfolioBonds(): Promise<PortfolioResponse> {
  const res = await fetch(`${API_BASE}/bonds`);
  if (!res.ok) throw new Error(`Failed to fetch portfolio bonds: ${res.status}`);
  return res.json();
}
