import type { ReactNode } from "react";
import type { Trend } from "@/types/bond-metrics";
import MetricTrend from "./MetricTrend";

interface Props {
  title: string;
  value: string;
  subtitle?: string;
  trend?: Trend;
  icon?: ReactNode;
}

export default function MetricCard({ title, value, subtitle, trend, icon }: Props) {
  return (
    <div className="space-y-1.5 rounded-lg border bg-card/50 p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon && <span className="h-3.5 w-3.5">{icon}</span>}
        {title}
      </div>
      <div className="text-2xl font-bold tabular-nums text-foreground">{value}</div>
      <div className="flex items-center gap-2">
        {subtitle && <span className="text-xs text-muted-foreground">{subtitle}</span>}
        {trend && <MetricTrend trend={trend} />}
      </div>
    </div>
  );
}
