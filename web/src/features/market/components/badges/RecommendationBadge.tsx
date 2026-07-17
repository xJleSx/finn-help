export type Recommendation = "buy" | "sell" | "hold" | "accumulate" | "reduce";

interface Props {
  recommendation: Recommendation;
}

const CONFIG: Record<Recommendation, { label: string; className: string }> = {
  buy: { label: "Покупать", className: "bg-emerald-500/15 text-emerald-500" },
  accumulate: { label: "Накопить", className: "bg-green-500/15 text-green-500" },
  hold: { label: "Держать", className: "bg-yellow-500/15 text-yellow-500" },
  reduce: { label: "Сократить", className: "bg-orange-500/15 text-orange-500" },
  sell: { label: "Продавать", className: "bg-red-500/15 text-red-500" },
};

export default function RecommendationBadge({ recommendation }: Props) {
  const cfg = CONFIG[recommendation] ?? CONFIG.hold;
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-bold ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}
