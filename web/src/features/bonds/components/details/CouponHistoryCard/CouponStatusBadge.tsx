import type { CouponStatus } from "@/features/bonds/types/coupon";

interface Props {
  status: CouponStatus;
}

const CONFIG: Record<CouponStatus, { label: string; className: string }> = {
  paid: { label: "Выплачен", className: "bg-emerald-500/15 text-emerald-500" },
  pending: { label: "Ожидается", className: "bg-yellow-500/15 text-yellow-500" },
  forecast: { label: "Прогноз", className: "bg-muted text-muted-foreground" },
};

export default function CouponStatusBadge({ status }: Props) {
  const cfg = CONFIG[status];
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}
