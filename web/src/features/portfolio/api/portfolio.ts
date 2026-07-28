import type { BondPortfolioResponse } from "@/features/portfolio/types/bond-summary";

const API_BASE = "/api/proxy/portfolio";

export type { BondPortfolioResponse as PortfolioResponse };

export async function getPortfolioBonds(): Promise<BondPortfolioResponse> {
  const res = await fetch(`${API_BASE}/bonds`);
  if (!res.ok) throw new Error(`Failed to fetch portfolio bonds: ${res.status}`);
  return res.json();
}
