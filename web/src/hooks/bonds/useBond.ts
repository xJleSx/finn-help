"use client";

import { useQuery } from "@tanstack/react-query";
import { getBonds } from "@/lib/api/bonds";
import { bondKeys } from "@/lib/query/keys";
import type { Bond } from "@/types/bond";

export function useBonds() {
  return useQuery<Bond[]>({
    queryKey: bondKeys.list(),
    queryFn: getBonds,
  });
}

export function useBond(ticker: string) {
  return useQuery<Bond>({
    queryKey: bondKeys.detail(ticker),
    queryFn: () => getBonds().then((bonds) => {
      const bond = bonds.find((b) => b.ticker === ticker);
      if (!bond) throw new Error(`Bond ${ticker} not found`);
      return bond;
    }),
    enabled: !!ticker,
  });
}
