"use client";

export default function ContributionBar({ plan, capital }: { plan: Record<string, any>; capital: number }) {
  const colors: Record<string, string> = { etf: "bg-amber-400", dividend: "bg-emerald-500", bond: "bg-orange-500", growth: "bg-violet-500" };
  const labels: Record<string, string> = { etf: "БПИФ", dividend: "Дивиденды", bond: "Облигации", growth: "Рост" };

  return (
    <div className="flex gap-0.5 h-2 rounded-full overflow-hidden">
      {Object.entries(plan).map(([key, cat]) => {
        const pct = (cat.budget / capital) * 100;
        return (
          <div
            key={key}
            className={`${colors[key] || "bg-gray-500"} transition-all hover:opacity-80`}
            style={{ width: `${pct}%` }}
            title={`${labels[key] || key}: ${pct.toFixed(1)}%`}
          />
        );
      })}
    </div>
  );
}
