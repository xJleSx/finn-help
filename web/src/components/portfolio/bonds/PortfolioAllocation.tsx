import { ArrowUp, ArrowDown, Minus } from "lucide-react";
import type { BondAllocation } from "@/types/portfolio/bond-allocation";

interface Props {
  allocation: BondAllocation;
}

const SEGMENTS = 20;

export default function PortfolioAllocation({ allocation }: Props) {
  const recFilled = Math.round((allocation.recommended / 100) * SEGMENTS);
  const actFilled = Math.round((allocation.actual / 100) * SEGMENTS);
  const diff = allocation.actual - allocation.recommended;

  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Распределение
      </h3>

      <div className="space-y-4">
        <div>
          <div className="mb-1.5 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Рекомендуемая</span>
            <span className="font-semibold tabular-nums">{allocation.recommended}%</span>
          </div>
          <div className="flex gap-0.5">
            {Array.from({ length: SEGMENTS }).map((_, i) => (
              <span
                key={i}
                className={`block h-2.5 flex-1 rounded-sm transition-colors ${
                  i < recFilled ? "bg-primary" : "bg-muted"
                }`}
              />
            ))}
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Фактическая</span>
            <span className="font-semibold tabular-nums">{allocation.actual}%</span>
          </div>
          <div className="flex gap-0.5">
            {Array.from({ length: SEGMENTS }).map((_, i) => (
              <span
                key={i}
                className={`block h-2.5 flex-1 rounded-sm transition-colors ${
                  i < actFilled ? "bg-emerald-500" : "bg-muted"
                }`}
              />
            ))}
          </div>
        </div>

        {diff !== 0 && (
          <div className={`flex items-center gap-1.5 rounded-lg border p-3 text-sm ${
            diff > 0
              ? "border-yellow-500/20 bg-yellow-500/5 text-yellow-500"
              : "border-blue-500/20 bg-blue-500/5 text-blue-500"
          }`}>
            {diff > 0 ? <ArrowUp className="h-4 w-4" /> : <ArrowDown className="h-4 w-4" />}
            <span>
              {diff > 0
                ? `Можно уменьшить долю на ${diff}%`
                : `Можно увеличить долю на ${Math.abs(diff)}%`}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
