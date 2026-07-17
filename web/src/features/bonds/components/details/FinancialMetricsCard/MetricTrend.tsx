import type { Trend } from "@/features/bonds/types/bond-metrics";

interface Props {
  trend: Trend;
}

const CONFIG: Record<Trend, { label: string; icon: string }> = {
  positive: { label: "выше средней", icon: "▲" },
  neutral: { label: "нейтрально", icon: "●" },
  negative: { label: "ниже средней", icon: "▼" },
};

export default function MetricTrend({ trend }: Props) {
  const cfg = CONFIG[trend];
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${
      trend === "positive" ? "text-emerald-500" : trend === "negative" ? "text-red-500" : "text-muted-foreground"
    }`}>
      <span className="text-[10px]">{cfg.icon}</span>
      {cfg.label}
    </span>
  );
}
