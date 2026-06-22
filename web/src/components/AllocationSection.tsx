"use client";

import { useState } from "react";
import type { AllocationPlan } from "./types";
import ContributionBar from "./ContributionBar";
import SectorBreakdown from "./SectorBreakdown";
import DonutChart from "./DonutChart";
import { api } from "../lib/api";

function formatCurrency(v: number) {
  return v.toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formatNumber(v: number, decimals = 2) {
  return v.toLocaleString("ru-RU", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export default function AllocationSection({ onSelectTicker }: { onSelectTicker: (t: string) => void }) {
  const [capital, setCapital] = useState("100000");
  const [allocation, setAllocation] = useState<AllocationPlan | null>(null);
  const [loadingAlloc, setLoadingAlloc] = useState(false);
  const [showAlloc, setShowAlloc] = useState(false);

  const fetchAllocation = async () => {
    setLoadingAlloc(true);
    try {
      const val = Math.max(500, parseFloat(capital) || 50000);
      const alloc = await api.portfolio.allocate(val);
      setAllocation(alloc);
      setCapital(String(val));
      setShowAlloc(true);
    } catch (e) {
      console.error("Allocation failed", e);
    } finally {
      setLoadingAlloc(false);
    }
  };

  const catColors: Record<string, string> = {
    etf: "border-l-amber-400", dividend: "border-l-emerald-500", bond: "border-l-orange-500", growth: "border-l-violet-500",
  };
  const catBarColors: Record<string, string> = {
    etf: "bg-amber-400", dividend: "bg-emerald-500", bond: "bg-orange-500", growth: "bg-violet-500",
  };
  const catLabels: Record<string, string> = {
    etf: "БПИФ", dividend: "Дивиденды", bond: "Облигации", growth: "Рост",
  };

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-6 backdrop-blur-sm transition-all duration-500 ease-out">
      <h2 className="text-lg font-light text-white mb-5">
        <span className="text-amber-400 font-medium">Собрать</span> пакет
      </h2>
      <div className="flex flex-wrap items-end gap-3 mb-6">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-gray-500 mb-1.5 font-mono">Сумма (₽)</label>
          <input
            type="number" value={capital} onChange={(e) => setCapital(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-lg font-mono text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/50 transition"
            min="500" step="100" placeholder="100000"
          />
        </div>
        <button onClick={fetchAllocation} disabled={loadingAlloc}
          className="px-8 py-3 rounded-xl font-medium text-sm transition-all duration-200 disabled:opacity-50"
          style={{ background: "linear-gradient(135deg, #F0B90B, #D4A107)", color: "#0B1A2F" }}>
          {loadingAlloc ? "Расчёт..." : "Рассчитать"}
        </button>
      </div>

      {allocation && (
        <div className="space-y-6 animate-fadeIn">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Капитал", value: formatCurrency(allocation.capital), color: "text-white" },
              { label: "Распределено", value: formatCurrency(allocation.total_allocated), color: "text-emerald-400" },
              { label: "Резерв", value: formatCurrency(allocation.reserve), color: "text-amber-400" },
              { label: "Доходность/мес", value: allocation.projected_monthly_yield > 0 ? `${formatNumber(allocation.projected_monthly_yield, 0)} ₽` : "—", color: "text-emerald-400" },
            ].map((m) => (
              <div key={m.label} className="bg-white/[0.03] rounded-xl p-3 text-center border border-white/5">
                <p className="text-xs text-gray-500 mb-1">{m.label}</p>
                <p className={`text-lg font-mono ${m.color}`}>{m.value}</p>
              </div>
            ))}
          </div>

          <ContributionBar plan={allocation.plan} capital={allocation.capital} />

          {allocation.sector_allocation && Object.keys(allocation.sector_allocation).length > 0 && (
            <SectorBreakdown sectors={allocation.sector_allocation} capital={allocation.capital} />
          )}

          <div className="flex flex-col lg:flex-row gap-6">
            <div className="flex-shrink-0 flex justify-center">
              <DonutChart plan={allocation.plan} capital={allocation.capital} />
            </div>
            <div className="flex-1 space-y-3 min-w-0">
              {Object.entries(allocation.plan).map(([key, cat]) => (
                <div key={key}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className={`w-2 h-2 rounded-full ${catBarColors[key] || "bg-gray-500"}`} />
                    <span className="text-sm font-medium text-white">{catLabels[key] || cat.label}</span>
                    <span className="text-xs text-gray-500 font-mono ml-auto">{formatCurrency(cat.budget)}</span>
                  </div>
                  {cat.items.map((item) => (
                    <div key={item.ticker}
                      className={`bg-white/[0.03] border border-white/5 rounded-xl p-3 pl-4 mb-1.5 border-l-4 ${catColors[key] || "border-l-gray-500"} hover:bg-white/[0.06] transition cursor-pointer`}
                      onClick={() => onSelectTicker(item.ticker)}>
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="font-mono text-sm text-white">{item.ticker}</span>
                          <span className="text-xs text-gray-500 ml-2">{item.name}</span>
                        </div>
                        <span className="font-mono text-sm text-white">{formatCurrency(item.amount)}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] text-gray-500">{item.reason}</span>
                        {item.expected_yield > 0 && (
                          <span className="text-[10px] text-emerald-400 font-mono">+{item.expected_yield.toFixed(1)}%</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
              <p className="text-[10px] text-gray-600 mt-3">
                Консервативное распределение: 40% БПИФ, 30% дивиденды, 20% облигации, 10% рост
              </p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
