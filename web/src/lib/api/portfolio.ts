import type { Bond } from "@/types/bond";

export interface PortfolioSummary {
  totalValue: number;
  totalInvested: number;
  totalPnL: number;
  bondCount: number;
}

export async function getPortfolio(): Promise<Bond[]> {
  const res = await fetch("/api/proxy/portfolio");
  if (!res.ok) throw new Error("Failed to fetch portfolio");
  return res.json();
}

export async function getPortfolioSummary(): Promise<PortfolioSummary> {
  const res = await fetch("/api/proxy/portfolio/summary");
  if (!res.ok) throw new Error("Failed to fetch portfolio summary");
  return res.json();
}

export async function addToPortfolio(ticker: string, quantity: number): Promise<void> {
  const res = await fetch("/api/proxy/portfolio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, quantity }),
  });
  if (!res.ok) throw new Error("Failed to add to portfolio");
}

export async function removeFromPortfolio(ticker: string): Promise<void> {
  const res = await fetch(`/api/proxy/portfolio/${ticker}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to remove from portfolio");
}
