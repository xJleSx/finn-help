"use client";

import { useQuery } from "@tanstack/react-query";
import { getBondCashFlow } from "@/lib/api/bonds";
import { bondKeys } from "@/lib/query/keys";
import type { CashFlowItemData, CashFlowSummaryData } from "@/types/cash-flow";

export function useBondCashFlow(ticker: string) {
  return useQuery<{ items: CashFlowItemData[]; summary: CashFlowSummaryData }>({
    queryKey: bondKeys.cashFlow(ticker),
    queryFn: () => getBondCashFlow(ticker),
    enabled: !!ticker,
  });
}
