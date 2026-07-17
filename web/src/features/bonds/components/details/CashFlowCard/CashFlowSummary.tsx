import type { CashFlowSummaryData } from "@/features/bonds/types/cash-flow";
import { formatCurrency, formatNumber } from "@/lib/format";

interface Props {
  summary: CashFlowSummaryData;
}

export default function CashFlowSummary({ summary }: Props) {
  return (
    <div className="grid grid-cols-2 gap-4 border-t border-border/50 pt-4 sm:grid-cols-4">
      <div className="space-y-0.5">
        <div className="text-xs text-muted-foreground">Всего выплат</div>
        <div className="text-base font-semibold tabular-nums text-foreground">
          {formatNumber(summary.totalPayments, 0)}
        </div>
      </div>
      <div className="space-y-0.5">
        <div className="text-xs text-muted-foreground">Осталось купонов</div>
        <div className="text-base font-semibold tabular-nums text-foreground">
          {formatNumber(summary.remainingCoupons, 0)}
        </div>
      </div>
      <div className="space-y-0.5">
        <div className="text-xs text-muted-foreground">Общий Cash Flow</div>
        <div className="text-base font-semibold tabular-nums text-foreground">
          {formatCurrency(summary.totalCashFlow)}
        </div>
      </div>
      <div className="space-y-0.5">
        <div className="text-xs text-muted-foreground">Средний купон</div>
        <div className="text-base font-semibold tabular-nums text-foreground">
          {formatCurrency(summary.averageCoupon)}
        </div>
      </div>
    </div>
  );
}
