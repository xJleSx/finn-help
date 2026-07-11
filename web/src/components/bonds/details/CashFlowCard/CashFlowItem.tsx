import type { CashFlowItemData, CashFlowType, CashFlowStatus } from "@/types/cash-flow";
import { formatCurrency } from "@/lib/format";

interface Props {
  item: CashFlowItemData;
  isLast?: boolean;
}

const TYPE_LABEL: Record<CashFlowType, string> = {
  coupon: "Купон",
  redemption: "Погашение",
};

const STATUS_COLORS: Record<CashFlowStatus, string> = {
  paid: "border-emerald-500/30 bg-emerald-500/5",
  expected: "border-yellow-500/30 bg-yellow-500/5",
  forecast: "border-border bg-card/50",
};

const DOT_COLORS: Record<CashFlowStatus, string> = {
  paid: "bg-emerald-500",
  expected: "bg-yellow-500",
  forecast: "bg-muted-foreground/30",
};

export default function CashFlowItem({ item, isLast }: Props) {
  const border = STATUS_COLORS[item.status];
  const dot = DOT_COLORS[item.status];
  const isRedemption = item.type === "redemption";

  return (
    <div className="relative flex gap-4">
      <div className="flex flex-col items-center">
        <div className={`z-10 h-3 w-3 rounded-full ${dot} ring-2 ring-background`} />
        {!isLast && <div className="mt-0.5 w-px flex-1 bg-border/50" />}
      </div>
      <div className={`mb-4 flex-1 rounded-lg border p-4 ${border}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {new Date(item.date).toLocaleDateString("ru-RU", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}
            </span>
            <span className={`text-xs font-medium ${
              item.status === "paid" ? "text-emerald-500" : item.status === "expected" ? "text-yellow-500" : "text-muted-foreground/50"
            }`}>
              {item.status === "paid" ? "Выплачен" : item.status === "expected" ? "Ожидается" : "Прогноз"}
            </span>
          </div>
          <span className={`text-sm font-semibold tabular-nums ${isRedemption ? "text-blue-500" : "text-foreground"}`}>
            {item.status === "paid" ? "" : "+"}{formatCurrency(item.amount)}
          </span>
        </div>
        <div className={`mt-1 text-xs font-medium ${isRedemption ? "text-blue-500" : "text-muted-foreground"}`}>
          {TYPE_LABEL[item.type]}
          {isRedemption && " + последний купон"}
        </div>
      </div>
    </div>
  );
}
