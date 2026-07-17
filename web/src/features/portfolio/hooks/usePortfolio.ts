import { useQuery } from "@tanstack/react-query";
import { getPortfolioBonds } from "../api/portfolio";

export function usePortfolioBonds() {
  return useQuery({
    queryKey: ["portfolio", "bonds"],
    queryFn: getPortfolioBonds,
    refetchInterval: 60_000,
  });
}
