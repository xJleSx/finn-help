"use client";

import { useQuery } from "@tanstack/react-query";
import { getBondPriceHistory } from "@/lib/api/bonds";
import { bondKeys } from "@/lib/query/keys";
import type { ChartData, ChartRange } from "@/types/chart";

export function useBondPriceHistory(ticker: string, range: ChartRange = "1M") {
  return useQuery<ChartData>({
    queryKey: bondKeys.priceHistory(ticker, range),
    queryFn: () => getBondPriceHistory(ticker, range),
    enabled: !!ticker,
  });
}
