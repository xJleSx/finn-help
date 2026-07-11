export const bondKeys = {
  all: ["bonds"] as const,
  list: () => [...bondKeys.all, "list"] as const,
  detail: (ticker: string) => [...bondKeys.all, "detail", ticker] as const,
  analysis: (ticker: string) => [...bondKeys.all, "analysis", ticker] as const,
  cashFlow: (ticker: string) => [...bondKeys.all, "cashFlow", ticker] as const,
  coupons: (ticker: string) => [...bondKeys.all, "coupons", ticker] as const,
  priceHistory: (ticker: string, range?: string) => [...bondKeys.all, "priceHistory", ticker, range].filter(Boolean) as readonly string[],
};
