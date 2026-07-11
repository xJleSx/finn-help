import type { ReactNode } from "react";

interface Props {
  label: string;
  value: ReactNode;
  change?: ReactNode;
}

export default function MetricItem({ label, value, change }: Props) {
  return (
    <div className="space-y-0.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className="text-base font-semibold tabular-nums text-foreground">{value}</span>
        {change && <span className="text-xs tabular-nums">{change}</span>}
      </div>
    </div>
  );
}
