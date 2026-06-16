"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type PricePoint = { date: string; close: number; volume?: number };

type SimulationResult = {
  mean_return: number; median_return: number; best_return: number; worst_return: number;
  var_95: number; cvar_95: number; upside_pct: number;
};

type Instrument = {
  id: number; ticker: string; full_name: string; type: string;
  last_price: number | null; last_date: string | null;
};

type PortfolioHolding = { ticker: string; name: string; shares: number; avg_price: number };

export default function PortfolioSimulator() {
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([
    { ticker: "SBER", name: "Сбер Банк", shares: 100, avg_price: 287.5 },
    { ticker: "GAZP", name: "Газпром", shares: 50, avg_price: 165.3 },
    { ticker: "LKOH", name: "Лукойл", shares: 10, avg_price: 7100 },
  ]);
  const [simResult, setSimResult] = useState<SimulationResult | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [newShares, setNewShares] = useState("0");
  const [newPrice, setNewPrice] = useState("0");
  const [instruments, setInstruments] = useState<Instrument[]>([]);

  useEffect(() => {
    fetch(`${API}/api/instruments?type=stock`).then((r) => r.json()).then(setInstruments).catch(() => {});
  }, []);

  const tickerNames: Record<string, string> = {};
  instruments.forEach((i) => { tickerNames[i.ticker] = i.full_name; });

  const addHolding = () => {
    const t = newTicker.toUpperCase().trim();
    if (!t || !tickerNames[t]) return;
    const s = Math.max(1, parseFloat(newShares) || 0);
    const p = Math.max(0.01, parseFloat(newPrice) || 0);
    setHoldings((prev) => {
      const existing = prev.find((h) => h.ticker === t);
      if (existing) return prev.map((h) => h.ticker === t ? { ...h, shares: h.shares + s, avg_price: (h.avg_price * h.shares + p * s) / (h.shares + s) } : h);
      return [...prev, { ticker: t, name: tickerNames[t] || t, shares: s, avg_price: p }];
    });
    setNewTicker(""); setNewShares("0"); setNewPrice("0");
  };

  const removeHolding = (ticker: string) => setHoldings((prev) => prev.filter((h) => h.ticker !== ticker));

  const runSimulation = async () => {
    if (holdings.length === 0) return;
    setSimulating(true); setSimResult(null);
    try {
      const histories: Record<string, number[]> = {};
      let minLen = Infinity;
      for (const h of holdings) {
        const res = await fetch(`${API}/api/instruments/${h.ticker}/prices?days=365`);
        if (!res.ok) continue;
        const data: PricePoint[] = await res.json();
        const closes = data.map((p) => p.close).filter((c) => c > 0);
        if (closes.length > 20) { histories[h.ticker] = closes; minLen = Math.min(minLen, closes.length); }
      }
      if (Object.keys(histories).length === 0 || minLen === Infinity) {
        setSimResult({ mean_return: 0, median_return: 0, best_return: 0, worst_return: 0, var_95: 0, cvar_95: 0, upside_pct: 0 });
        return;
      }
      const totalInvestment = holdings.reduce((s, h) => s + h.shares * h.avg_price, 0);
      const weights = holdings.map((h) => (h.shares * h.avg_price) / totalInvestment);
      const dailyReturns: number[] = [];
      for (let i = 1; i < minLen; i++) {
        let portRet = 0;
        for (let j = 0; j < holdings.length; j++) {
          const h = holdings[j]; const vals = histories[h.ticker];
          if (vals && i < vals.length) portRet += ((vals[i] - vals[i - 1]) / vals[i - 1]) * weights[j];
        }
        dailyReturns.push(portRet);
      }
      let s = 42;
      const next = () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
      const simResults: number[] = [];
      for (let sim = 0; sim < 500; sim++) { let cum = 1; for (let d = 0; d < 252; d++) cum *= 1 + dailyReturns[Math.floor(next() * dailyReturns.length)]; simResults.push(cum - 1); }
      simResults.sort((a, b) => a - b);
      const idx5 = Math.floor(500 * 0.05);
      setSimResult({
        mean_return: simResults.reduce((a, b) => a + b, 0) / 500,
        median_return: simResults[250], best_return: simResults[499], worst_return: simResults[0],
        var_95: simResults[idx5], cvar_95: simResults.slice(0, idx5).reduce((a, b) => a + b, 0) / Math.max(idx5, 1),
        upside_pct: simResults.filter((r) => r > 0).length / 500,
      });
    } catch { setSimResult(null); }
    finally { setSimulating(false); }
  };

  const totalValue = holdings.reduce((s, h) => s + h.shares * h.avg_price, 0);

  return (
    <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h2 className="text-sm font-light text-white mb-4"><span className="text-amber-400 font-medium">Портфель</span> — симулятор</h2>
      <div className="space-y-2 mb-4">
        {holdings.map((h) => (
          <div key={h.ticker} className="flex items-center gap-3 bg-white/[0.03] rounded-xl p-3 border border-white/5">
            <div className="flex-1 min-w-0">
              <span className="font-mono text-sm text-white">{h.ticker}</span>
              <span className="text-xs text-gray-500 ml-2">{h.name}</span>
            </div>
            <span className="font-mono text-xs text-gray-400">{h.shares} шт.</span>
            <span className="font-mono text-xs text-gray-400">× {h.avg_price.toFixed(1)} ₽</span>
            <span className="font-mono text-sm text-white min-w-[80px] text-right">{(h.shares * h.avg_price).toLocaleString()} ₽</span>
            <button onClick={() => removeHolding(h.ticker)} className="text-red-400/60 hover:text-red-400 text-xs p-1">✕</button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 items-center mb-4">
        <input value={newTicker} onChange={(e) => setNewTicker(e.target.value.toUpperCase())} placeholder="SBER" list="sim-tickers" className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs font-mono text-white w-20 focus:outline-none focus:border-amber-400/50" />
        <datalist id="sim-tickers">{instruments.map((i) => <option key={i.id} value={i.ticker} />)}</datalist>
        <input type="number" value={newShares} onChange={(e) => setNewShares(e.target.value)} placeholder="шт" className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs font-mono text-white w-20 focus:outline-none focus:border-amber-400/50" min="1" />
        <input type="number" value={newPrice} onChange={(e) => setNewPrice(e.target.value)} placeholder="₽" className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs font-mono text-white w-24 focus:outline-none focus:border-amber-400/50" min="1" />
        <button onClick={addHolding} className="px-4 py-2 rounded-lg text-xs font-medium bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 transition">+</button>
      </div>
      <div className="flex items-center gap-3">
        <button onClick={runSimulation} disabled={simulating || holdings.length === 0} className="px-5 py-2 rounded-xl text-xs font-medium transition disabled:opacity-30" style={{ background: "linear-gradient(135deg, #F0B90B, #D4A107)", color: "#0B1A2F" }}>
          {simulating ? "Симуляция..." : `Monte-Carlo 500 × 252д (${totalValue.toLocaleString()} ₽)`}
        </button>
      </div>
      {simResult && (
        <div className="grid grid-cols-4 gap-2 mt-4">
          <div className="bg-white/[0.03] rounded-xl p-2.5 text-center border border-white/5">
            <p className="text-[10px] text-gray-500">Средняя</p>
            <p className={`text-sm font-mono ${simResult.mean_return > 0 ? "text-emerald-400" : "text-red-400"}`}>{(simResult.mean_return * 100).toFixed(1)}%</p>
          </div>
          <div className="bg-white/[0.03] rounded-xl p-2.5 text-center border border-white/5">
            <p className="text-[10px] text-gray-500">Медиана</p>
            <p className={`text-sm font-mono ${simResult.median_return > 0 ? "text-emerald-400" : "text-red-400"}`}>{(simResult.median_return * 100).toFixed(1)}%</p>
          </div>
          <div className="bg-white/[0.03] rounded-xl p-2.5 text-center border border-white/5">
            <p className="text-[10px] text-gray-500">VaR 95%</p>
            <p className={`text-sm font-mono ${simResult.var_95 > 0 ? "text-emerald-400" : "text-red-400"}`}>{(simResult.var_95 * 100).toFixed(1)}%</p>
          </div>
          <div className="bg-white/[0.03] rounded-xl p-2.5 text-center border border-white/5">
            <p className="text-[10px] text-gray-500">Успех</p>
            <p className="text-sm font-mono text-emerald-400">{(simResult.upside_pct * 100).toFixed(0)}%</p>
          </div>
        </div>
      )}
    </div>
  );
}
