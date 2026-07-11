export type CouponStatus = "paid" | "pending" | "forecast";

export interface CouponPayment {
  id: string;
  date: string;
  amount: number;
  status: CouponStatus;
}
