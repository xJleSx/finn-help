import { formatCurrency } from "@/lib/format";

export interface CashFlowEvent {
  month: string;
  amount: number;
}

interface Props {
  events: CashFlowEvent[];
}

export default function PortfolioCashFlow({ events }: Props) {
  if (events.length === 0) return null;

  const total = events.reduce((s, e) => s + e.amount, 0);
  const maxAmount = Math.max(...events.map((e) => e.amount));

  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Cash Flow
      </h3>

      <div className="space-y-3">
        {events.map((e, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="w-24 shrink-0 text-xs text-muted-foreground">
              {e.month}
            </div>
            <div className="flex-1">
              <div className="flex h-6 items-center">
                <div
                  className="h-4 rounded-r-sm bg-emerald-500/60 transition-all"
                  style={{ width: `${(e.amount / maxAmount) * 100}%` }}
                />
              </div>
            </div>
            <div className="w-20 shrink-0 text-right text-sm font-semibold tabular-nums text-foreground">
              {formatCurrency(e.amount)}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-3">
        <span className="text-xs text-muted-foreground">Всего за период</span>
        <span className="text-sm font-semibold tabular-nums text-foreground">
          {formatCurrency(total)}
        </span>
      </div>
    </div>
  );
}
