import type { CouponPayment } from "@/types/coupon";
import CouponHistoryTable from "./CouponHistoryTable";

interface Props {
  payments: CouponPayment[];
}

export default function CouponHistoryCard({ payments }: Props) {
  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        История купонных выплат
      </h3>
      <CouponHistoryTable payments={payments} />
    </div>
  );
}
