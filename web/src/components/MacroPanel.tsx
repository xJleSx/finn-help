"use client";

import type { MacroData } from "./types";

type Props = {
  data: MacroData | null;
};

export default function MacroPanel({ data }: Props) {
  const items = [
    { label: "Brent", value: data?.brent?.toFixed(1) ?? "—" },
    { label: "USD/RUB", value: data?.usd_rate?.toFixed(2) ?? "—" },
    { label: "IMOEX", value: data?.imoex?.toFixed(0) ?? "—" },
    { label: "Ключевая ставка", value: data?.key_rate != null ? `${data.key_rate}%` : "—" },
    { label: "Инфляция", value: data?.cpi != null ? `${data.cpi}%` : "—" },
  ];

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h3 className="text-sm font-light text-white mb-3">Макро</h3>
      <div className="text-xs text-gray-400 space-y-1.5">
        {items.map(({ label, value }) => (
          <div key={label} className="flex justify-between">
            <span>{label}</span>
            <span className="font-mono text-white">{value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
