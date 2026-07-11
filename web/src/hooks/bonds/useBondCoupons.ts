"use client";

import { useQuery } from "@tanstack/react-query";
import { getBondCoupons } from "@/lib/api/bonds";
import { bondKeys } from "@/lib/query/keys";
import type { CouponPayment } from "@/types/coupon";

export function useBondCoupons(ticker: string) {
  return useQuery<CouponPayment[]>({
    queryKey: bondKeys.coupons(ticker),
    queryFn: () => getBondCoupons(ticker),
    enabled: !!ticker,
  });
}
