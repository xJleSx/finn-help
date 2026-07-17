"use client";

import { useQuery } from "@tanstack/react-query";
import { getBondAnalysis, getAIAnalysis, getBondMetrics } from "@/features/bonds/api/bonds";
import { bondKeys } from "@/lib/query/keys";
import type { BondAnalysis } from "@/features/bonds/types/bond-analysis";
import type { AIAnalysis } from "@/features/bonds/types/ai-analysis";
import type { BondMetrics } from "@/features/bonds/types/bond-metrics";

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
