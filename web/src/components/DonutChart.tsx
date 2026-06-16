"use client";

type AllocationCategory = {
  label: string; budget: number; items: { ticker: string; name: string; amount: number; reason: string; expected_yield: number }[];
};

export default function DonutChart({ plan, capital }: { plan: Record<string, AllocationCategory>; capital: number }) {
  const entries = Object.entries(plan);
  const colors = ["#F0B90B", "#10B981", "#F97316", "#8B5CF6", "#6B7280"];
  const labels: Record<string, string> = { etf: "БПИФ", dividend: "Дивиденды", bond: "Облигации", growth: "Рост" };

  let cumulative = 0;
  const segments = entries.map(([key, cat], i) => {
    const pct = cat.budget / capital;
    const start = cumulative;
    cumulative += pct;
    return { key, pct, start, color: colors[i % colors.length], label: labels[key] || cat.label };
  });

  const R = 120;
  const cx = 150;
  const cy = 150;

  return (
    <svg width={300} height={300} viewBox="0 0 300 300" className="drop-shadow-lg">
      {segments.map((seg, i) => {
        const p = seg.pct * 360;
        const s = seg.start * 360;
        const sr = (s - 90) * (Math.PI / 180);
        const er = (s + p - 90) * (Math.PI / 180);
        const x1 = cx + R * Math.cos(sr);
        const y1 = cy + R * Math.sin(sr);
        const x2 = cx + R * Math.cos(er);
        const y2 = cy + R * Math.sin(er);
        const large = p > 180 ? 1 : 0;
        return (
          <path
            key={seg.key}
            d={`M ${cx} ${cy} L ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} Z`}
            fill={seg.color}
            opacity={0.85}
            className="hover:opacity-100 transition-opacity cursor-pointer"
          >
            <title>{seg.label}: {(seg.pct * capital).toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0 })} ({(seg.pct * 100).toFixed(0)}%)</title>
          </path>
        );
      })}
      <circle cx={cx} cy={cy} r={60} fill="#0B1A2F" />
      <text x={cx} y={cy - 8} textAnchor="middle" fill="#fff" className="text-xs font-mono" fontSize={14}>
        {capital.toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0 })}
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill="#9CA3AF" className="text-xs" fontSize={11}>
        всего
      </text>
    </svg>
  );
}
