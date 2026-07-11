"use client";

import { useQuery } from "@tanstack/react-query";
import { getBondAnalysis, getAIAnalysis, getBondMetrics } from "@/lib/api/bonds";
import { bondKeys } from "@/lib/query/keys";
import type { BondAnalysis } from "@/types/bond-analysis";
import type { AIAnalysis } from "@/types/ai-analysis";
import type { BondMetrics } from "@/types/bond-metrics";

export function useBondAnalysis(ticker: string) {
  return useQuery<BondAnalysis>({
    queryKey: bondKeys.analysis(ticker),
    queryFn: () => getBondAnalysis(ticker),
    enabled: !!ticker,
  });
}

export function useAIAnalysis(ticker: string) {
  return useQuery<AIAnalysis>({
    queryKey: [...bondKeys.analysis(ticker), "ai"],
    queryFn: () => getAIAnalysis(ticker),
    enabled: !!ticker,
  });
}

export function useBondMetrics(ticker: string) {
  return useQuery<BondMetrics>({
    queryKey: [...bondKeys.analysis(ticker), "metrics"],
    queryFn: () => getBondMetrics(ticker),
    enabled: !!ticker,
  });
}
