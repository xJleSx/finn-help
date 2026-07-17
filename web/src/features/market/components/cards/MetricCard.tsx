import type { ReactNode } from "react";

interface Props {
  title: string;
  value: string;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
  icon?: ReactNode;
  className?: string;
}

export default function MetricCard({ title, value, subtitle, trend, icon, className = "" }: Props) {
  return (
    <div className={`space-y-1.5 rounded-lg border bg-card/50 p-4 ${className}`}>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon && <span className="h-3.5 w-3.5">{icon}</span>}
        {title}
      </div>
      <div className="text-2xl font-bold tabular-nums text-foreground">{value}</div>
      {subtitle && (
        <div className={`flex items-center gap-1 text-xs ${
          trend === "up" ? "text-emerald-500" : trend === "down" ? "text-red-500" : "text-muted-foreground"
        }`}>
          {trend === "up" && "▲"}
          {trend === "down" && "▼"}
          {subtitle}
        </div>
      )}
    </div>
  );
}
