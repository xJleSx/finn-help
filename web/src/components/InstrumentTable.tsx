"use client";

import type { Instrument } from "./types";

export default function InstrumentTable({ instruments, onSelectTicker }: {
  instruments: Instrument[]; onSelectTicker: (t: string) => void;
}) {
  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4">Инструменты</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-600 border-b border-white/5">
              <th className="text-left py-2 font-mono text-xs">Тикер</th>
              <th className="text-left py-2 font-mono text-xs">Название</th>
              <th className="text-right py-2 font-mono text-xs">Цена</th>
            </tr>
          </thead>
          <tbody>
            {instruments.slice(0, 20).map((i) => (
              <tr key={i.id} className="border-b border-white/5 hover:bg-white/[0.02] cursor-pointer transition"
                onClick={() => onSelectTicker(i.ticker)}>
                <td className="py-2.5 font-mono text-amber-400/80 text-xs">{i.ticker}</td>
                <td className="py-2.5 text-xs text-gray-300">{i.full_name}</td>
                <td className="py-2.5 text-right font-mono text-xs text-white">
                  {i.last_price !== null ? `${i.last_price.toFixed(2)} ₽` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
