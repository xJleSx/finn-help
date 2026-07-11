export interface MarketIndex {
  name: string;
  value: number;
  change: number;
}

export async function getMarketIndices(): Promise<MarketIndex[]> {
  const res = await fetch("/api/proxy/market/indices");
  if (!res.ok) throw new Error("Failed to fetch market indices");
  return res.json();
}

export async function getMarketNews(): Promise<unknown[]> {
  const res = await fetch("/api/proxy/market/news");
  if (!res.ok) throw new Error("Failed to fetch market news");
  return res.json();
}
