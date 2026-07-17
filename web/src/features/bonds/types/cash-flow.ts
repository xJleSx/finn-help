export type CashFlowType = "coupon" | "redemption";

export type CashFlowStatus = "paid" | "expected" | "forecast";

export interface CashFlowItemData {
  id: string;
  date: string;
  amount: number;
  type: CashFlowType;
  status: CashFlowStatus;
}

export interface CashFlowSummaryData {
  totalPayments: number;
  remainingCoupons: number;
  totalCashFlow: number;
  averageCoupon: number;
  maturityDate: string;
}
