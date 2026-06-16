"use client";

export default function SectorBreakdown({ sectors, capital }: { sectors: Record<string, number>; capital: number }) {
  const sectorColors: Record<string, string> = {
    Финансы: "bg-blue-500", Нефть: "bg-yellow-600", Металлы: "bg-orange-500",
    IT: "bg-purple-500", Потребительский: "bg-pink-500", Телеком: "bg-cyan-500",
    Энергетика: "bg-red-500", Химия: "bg-green-600", Транспорт: "bg-indigo-500",
    Строительство: "bg-amber-700",
  };
  const total = Object.values(sectors).reduce((a, b) => a + b, 0) || 1;
  const entries = Object.entries(sectors).sort((a, b) => b[1] - a[1]);

  return (
    <div className="bg-white/[0.03] border border-white/5 rounded-xl p-4">
      <h3 className="text-xs font-medium text-gray-400 mb-3">Сектора</h3>
      <div className="flex gap-0.5 h-2 rounded-full overflow-hidden mb-3">
        {entries.map(([sector, amount]) => (
          <div
            key={sector}
            className={`${sectorColors[sector] || "bg-gray-500"} transition-all hover:opacity-80`}
            style={{ width: `${(amount / total) * 100}%` }}
            title={`${sector}: ${amount.toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0 })}`}
          />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {entries.map(([sector, amount]) => (
          <div key={sector} className="flex items-center gap-2 text-xs">
            <div className={`w-2 h-2 rounded-full ${sectorColors[sector] || "bg-gray-500"} flex-shrink-0`} />
            <span className="text-gray-400 truncate">{sector}</span>
            <span className="font-mono text-white ml-auto">{amount.toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0 })}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
