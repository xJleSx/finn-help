"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api-client";

export default function InstrumentsPage() {
  const [type, setType] = useState("stock");

  const { data: instruments, isLoading } = useQuery({
    queryKey: ["instruments", type],
    queryFn: () => api.instruments.list(type),
    refetchInterval: 60_000,
  });

  const types = [
    { value: "stock", label: "Акции" },
    { value: "bond", label: "Облигации" },
    { value: "etf", label: "БПИФ" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-light text-white">Инструменты</h1>
          <p className="text-sm text-gray-500 mt-1">MOEX — акции, облигации, БПИФ</p>
        </div>
        <div className="flex bg-white/5 rounded-lg p-0.5">
          {types.map((t) => (
            <button
              key={t.value}
              onClick={() => setType(t.value)}
              className={`px-3 py-1.5 text-xs rounded-md transition ${
                type === t.value ? "bg-amber-400/20 text-amber-400" : "text-gray-500 hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-12 bg-white/5 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="bg-white/[0.04] border border-white/10 rounded-2xl overflow-hidden backdrop-blur-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-600 border-b border-white/5">
                <th className="text-left py-3 px-4 font-mono text-xs">Тикер</th>
                <th className="text-left py-3 px-4 font-mono text-xs">Название</th>
                <th className="text-right py-3 px-4 font-mono text-xs">Цена</th>
                <th className="text-right py-3 px-4 font-mono text-xs">Сектор</th>
              </tr>
            </thead>
            <tbody>
              {(instruments ?? []).map((inst) => (
                <tr
                  key={inst.id}
                  className="border-b border-white/5 hover:bg-white/[0.02] transition"
                >
                  <td className="py-3 px-4">
                    <Link
                      href={`/instruments/${inst.ticker}`}
                      className="font-mono text-amber-400/80 text-xs hover:text-amber-400 transition"
                    >
                      {inst.ticker}
                    </Link>
                  </td>
                  <td className="py-3 px-4 text-xs text-gray-300">{inst.full_name}</td>
                  <td className="py-3 px-4 text-right font-mono text-xs text-white">
                    {inst.last_price !== null ? `${inst.last_price.toFixed(2)} ₽` : "—"}
                  </td>
                  <td className="py-3 px-4 text-right text-xs text-gray-500">
                    {inst.sector || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
