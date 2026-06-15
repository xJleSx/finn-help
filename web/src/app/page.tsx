"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type Instrument = {
  id: number;
  ticker: string;
  full_name: string;
  type: string;
  last_price: number | null;
  last_date: string | null;
};

type News = {
  id: number;
  title: string;
  summary: string;
  source: string;
  url: string;
  published_at: string | null;
};

type GeoRisk = {
  date: string;
  score: number;
};

type DashboardData = {
  instruments: number;
  signals: number;
  last_update: string | null;
  timestamp: string;
};

type AllocationItem = {
  ticker: string;
  name: string;
  amount: number;
  reason: string;
  expected_yield: number;
};

type AllocationCategory = {
  label: string;
  budget: number;
  items: AllocationItem[];
};

type AllocationPlan = {
  capital: number;
  total_allocated: number;
  reserve: number;
  plan: Record<string, AllocationCategory>;
  projected_monthly_yield: number;
  projected_monthly_pct: number;
  existing_portfolio: { ticker: string; quantity: number; current_value: number }[];
  sector_allocation: Record<string, number>;
};

type PricePoint = {
  date: string;
  close: number;
  volume?: number;
};

type UserInfo = {
  id: number;
  username: string;
  email: string | null;
  role: string;
  risk_profile: string;
  is_active: boolean;
};

type AuthState = {
  token: string | null;
  user: UserInfo | null;
};

type SimulationResult = {
  mean_return: number;
  median_return: number;
  best_return: number;
  worst_return: number;
  var_95: number;
  cvar_95: number;
  upside_pct: number;
};

type PortfolioHolding = {
  ticker: string;
  name: string;
  shares: number;
  avg_price: number;
};

function formatCurrency(v: number) {
  return v.toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formatNumber(v: number, decimals = 2) {
  return v.toLocaleString("ru-RU", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function authHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

async function apiPost(url: string, body: unknown, token?: string | null): Promise<any> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token || null) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

const AUTH_KEY = "finn_auth";

function loadAuth(): AuthState {
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { token: null, user: null };
}

function saveAuth(auth: AuthState) {
  localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
}

function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
}

function AuthModal({ onClose, onAuth }: { onClose: () => void; onAuth: (s: AuthState) => void }) {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [riskProfile, setRiskProfile] = useState("balanced");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setError(""); setLoading(true);
    try {
      if (tab === "register") {
        const data = await apiPost(`${API}/api/auth/register`, { username, password, risk_profile: riskProfile });
        const userRes = await fetch(`${API}/api/auth/me`, { headers: authHeaders(data.access_token) });
        const user = await userRes.json();
        const state: AuthState = { token: data.access_token, user };
        saveAuth(state);
        onAuth(state);
      } else {
        const data = await apiPost(`${API}/api/auth/login`, { username, password });
        const userRes = await fetch(`${API}/api/auth/me`, { headers: authHeaders(data.access_token) });
        const user = await userRes.json();
        const state: AuthState = { token: data.access_token, user };
        saveAuth(state);
        onAuth(state);
      }
    } catch (e: any) {
      setError(e.message || "Ошибка");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[#0B1A2F] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4 backdrop-blur-sm" onClick={(e) => e.stopPropagation()}>
        <div className="flex gap-0 mb-5 bg-white/5 rounded-xl p-0.5">
          <button onClick={() => setTab("login")} className={`flex-1 py-2 text-xs font-medium rounded-lg transition ${tab === "login" ? "bg-amber-400/20 text-amber-400" : "text-gray-500"}`}>Вход</button>
          <button onClick={() => setTab("register")} className={`flex-1 py-2 text-xs font-medium rounded-lg transition ${tab === "register" ? "bg-amber-400/20 text-amber-400" : "text-gray-500"}`}>Регистрация</button>
        </div>
        <div className="space-y-3">
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Логин" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/50" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Пароль" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/50" />
          {tab === "register" && (
            <select value={riskProfile} onChange={(e) => setRiskProfile(e.target.value)} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono text-white focus:outline-none focus:border-amber-400/50">
              <option value="conservative">Консервативный</option>
              <option value="balanced">Умеренный</option>
              <option value="aggressive">Агрессивный</option>
            </select>
          )}
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button onClick={handleSubmit} disabled={loading || !username || !password}
            className="w-full py-3 rounded-xl font-medium text-sm transition disabled:opacity-40"
            style={{ background: "linear-gradient(135deg, #F0B90B, #D4A107)", color: "#0B1A2F" }}>
            {loading ? "..." : tab === "login" ? "Войти" : "Зарегистрироваться"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DonutChart({ plan, reserve, capital }: { plan: Record<string, AllocationCategory>; reserve: number; capital: number }) {
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
            <title>{seg.label}: {formatCurrency(seg.pct * capital)} ({(seg.pct * 100).toFixed(0)}%)</title>
          </path>
        );
      })}
      <circle cx={cx} cy={cy} r={60} fill="#0B1A2F" />
      <text x={cx} y={cy - 8} textAnchor="middle" fill="#fff" className="text-xs font-mono" fontSize={14}>
        {formatCurrency(capital)}
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill="#9CA3AF" className="text-xs" fontSize={11}>
        всего
      </text>
    </svg>
  );
}

function ContributionBar({ plan, capital }: { plan: Record<string, AllocationCategory>; capital: number }) {
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

function SectorBreakdown({ sectors, capital }: { sectors: Record<string, number>; capital: number }) {
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
            title={`${sector}: ${formatCurrency(amount)}`}
          />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {entries.map(([sector, amount]) => (
          <div key={sector} className="flex items-center gap-2 text-xs">
            <div className={`w-2 h-2 rounded-full ${sectorColors[sector] || "bg-gray-500"} flex-shrink-0`} />
            <span className="text-gray-400 truncate">{sector}</span>
            <span className="font-mono text-white ml-auto">{formatCurrency(amount)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PortfolioSimulator() {
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
  const tickers = instruments.map((i) => i.ticker);

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
    setNewTicker("");
    setNewShares("0");
    setNewPrice("0");
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
      const seed = 42; let s = seed;
      const next = () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
      const simResults: number[] = [];
      for (let sim = 0; sim < 500; sim++) { let cum = 1; for (let d = 0; d < 252; d++) cum *= 1 + dailyReturns[Math.floor(next() * dailyReturns.length)]; simResults.push(cum - 1); }
      simResults.sort((a, b) => a - b);
      const idx5 = Math.floor(500 * 0.05);
      setSimResult({
        mean_return: simResults.reduce((a, b) => a + b, 0) / 500,
        median_return: simResults[250],
        best_return: simResults[499],
        worst_return: simResults[0],
        var_95: simResults[idx5],
        cvar_95: simResults.slice(0, idx5).reduce((a, b) => a + b, 0) / Math.max(idx5, 1),
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

function PriceChart({ ticker, company }: { ticker: string; company: string }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [period, setPeriod] = useState("1M");
  const [showSMA, setShowSMA] = useState(false);

  useEffect(() => {
    const daysMap: Record<string, number> = { "1Н": 7, "1М": 30, "3М": 90, "1Г": 365 };
    const days = daysMap[period] || 30;
    fetch(`${API}/api/instruments/${ticker}/prices?days=${days}`)
      .then((r) => r.json())
      .then(setPrices)
      .catch(() => setPrices([]));
  }, [ticker, period]);

  useEffect(() => {
    if (!chartRef.current || prices.length === 0) return;
    let chart: any, line: any, smaLine: any;

    import("lightweight-charts").then((lc) => {
      chart = lc.createChart(chartRef.current!, {
        width: chartRef.current!.clientWidth,
        height: 280,
        layout: { background: { type: lc.ColorType.Solid, color: "transparent" } as any, textColor: "#9CA3AF" },
        grid: { vertLines: { color: "rgba(255,255,255,0.03)" }, horzLines: { color: "rgba(255,255,255,0.03)" } },
        crosshair: { vertLine: { color: "#F0B90B", width: 1, style: 2 }, horzLine: { color: "#F0B90B", width: 1, style: 2 } },
        timeScale: { borderColor: "rgba(255,255,255,0.08)" },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      });

      const data = prices.map((p) => ({ time: p.date.slice(0, 10), value: p.close }));
      line = chart.addLineSeries({ color: "#F0B90B", lineWidth: 2, crosshairMarkerVisible: true });
      line.setData(data);

      if (showSMA) {
        const smaData = data.map((d, i, arr) => {
          if (i < 19) return d;
          const vals = arr.slice(i - 19, i + 1).map((x) => x.value);
          return { ...d, value: vals.reduce((a, b) => a + b, 0) / vals.length };
        });
        smaLine = chart.addLineSeries({ color: "#10B981", lineWidth: 1, lineStyle: 2 });
        smaLine.setData(smaData);
      }

      const handleResize = () => {
        if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
      };
      window.addEventListener("resize", handleResize);
      return () => {
        window.removeEventListener("resize", handleResize);
        chart.remove();
      };
    });
  }, [prices, showSMA]);

  const periods = ["1Н", "1М", "3М", "1Г"];

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">{ticker} — {company}</h3>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={showSMA} onChange={(e) => setShowSMA(e.target.checked)} className="accent-amber-400" />
            SMA 20
          </label>
          <div className="flex bg-white/5 rounded-lg p-0.5">
            {periods.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-2.5 py-1 text-xs rounded-md transition ${period === p ? "bg-amber-400/20 text-amber-400" : "text-gray-500 hover:text-white"}`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div ref={chartRef} className="w-full" />
    </div>
  );
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [news, setNews] = useState<News[]>([]);
  const [geoHistory, setGeoHistory] = useState<GeoRisk[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string>("SBER");
  const [advice, setAdvice] = useState<string>("");

  const [capital, setCapital] = useState("100000");
  const [allocation, setAllocation] = useState<AllocationPlan | null>(null);
  const [loadingAlloc, setLoadingAlloc] = useState(false);
  const [showAlloc, setShowAlloc] = useState(false);

  const [auth, setAuth] = useState<AuthState>({ token: null, user: null });
  const [showAuth, setShowAuth] = useState(false);

  useEffect(() => {
    const saved = loadAuth();
    if (saved.token) setAuth(saved);
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [instRes, newsRes, geoRes] = await Promise.all([
          fetch(`${API}/api/instruments?type=stock`),
          fetch(`${API}/api/news?limit=5`),
          fetch(`${API}/api/geo-risk?days=14`),
        ]);
        setInstruments(await instRes.json());
        setNews(await newsRes.json());
        setGeoHistory(await geoRes.json());
      } catch (e) {
        console.error("Failed to fetch data", e);
      }
    };
    const fetchEvents = () => {
      const es = new EventSource(`${API}/api/events`);
      es.onmessage = (e) => setDashboard(JSON.parse(e.data));
      es.onerror = () => {};
      return () => es.close();
    };
    fetchData();
    return fetchEvents();
  }, []);

  const fetchAdvice = useCallback(async (ticker: string) => {
    try {
      const res = await fetch(`${API}/api/instruments/${ticker}/advice`);
      if (!res.ok) return;
      const data = await res.json();
      setAdvice(data.advice || JSON.stringify(data.signal, null, 2));
    } catch {
      setAdvice("API недоступен");
    }
  }, []);

  useEffect(() => {
    fetchAdvice(selectedTicker);
  }, [selectedTicker, fetchAdvice]);

  const fetchAllocation = async () => {
    setLoadingAlloc(true);
    try {
      const val = Math.max(500, parseFloat(capital) || 50000);
      const res = await fetch(`${API}/api/portfolio/allocate?capital=${val}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      setAllocation(await res.json());
      setCapital(String(val));
      setShowAlloc(true);
    } catch (e) {
      console.error("Allocation failed", e);
    } finally {
      setLoadingAlloc(false);
    }
  };

  const latestGeo = geoHistory[geoHistory.length - 1];
  const selectedInst = instruments.find((i) => i.ticker === selectedTicker);

  const catColors: Record<string, string> = {
    etf: "border-l-amber-400",
    dividend: "border-l-emerald-500",
    bond: "border-l-orange-500",
    growth: "border-l-violet-500",
  };
  const catBarColors: Record<string, string> = {
    etf: "bg-amber-400",
    dividend: "bg-emerald-500",
    bond: "bg-orange-500",
    growth: "bg-violet-500",
  };
  const catLabels: Record<string, string> = {
    etf: "БПИФ",
    dividend: "Дивиденды",
    bond: "Облигации",
    growth: "Рост",
  };

  return (
    <div className="min-h-screen" style={{ background: "#0B1A2F" }}>
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6 animate-fadeIn">
        <header className="flex items-center justify-between bg-white/[0.04] border border-white/10 rounded-2xl px-6 py-4 backdrop-blur-sm">
          <div>
            <h1 className="text-2xl font-light tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
              Fin<span className="text-amber-400 font-medium">Advisor</span>
            </h1>
            <p className="text-gray-500 text-xs mt-0.5">AI финансовый ассистент для MOEX</p>
          </div>
          {dashboard && (
            <div className="flex gap-5 text-xs">
              <div className="text-right">
                <p className="text-gray-500">Инструментов</p>
                <p className="font-mono text-white">{dashboard.instruments}</p>
              </div>
              <div className="text-right">
                <p className="text-gray-500">Сигналов</p>
                <p className="font-mono text-white">{dashboard.signals}</p>
              </div>
              {latestGeo && (
                <div className="text-right">
                  <p className="text-gray-500">GeoRisk</p>
                  <p className={`font-mono ${latestGeo.score > 7 ? "text-red-400" : latestGeo.score > 5 ? "text-amber-400" : "text-emerald-400"}`}>
                    {latestGeo.score.toFixed(1)}
                  </p>
                </div>
              )}
            </div>
          )}
          <div className="flex items-center gap-3">
            {auth.user ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">{auth.user.username}</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-400/10 text-amber-400">
                  {auth.user.risk_profile === "conservative" ? "Конс" : auth.user.risk_profile === "aggressive" ? "Агр" : "Умер"}
                </span>
                <button onClick={() => { clearAuth(); setAuth({ token: null, user: null }); }}
                  className="text-xs text-gray-500 hover:text-red-400 transition ml-1">Выйти</button>
              </div>
            ) : (
              <button onClick={() => setShowAuth(true)}
                className="px-4 py-1.5 rounded-lg text-xs font-medium transition border border-amber-400/30 text-amber-400 hover:bg-amber-400/10">
                Войти
              </button>
            )}
          </div>
        </header>

        <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-6 backdrop-blur-sm transition-all duration-500 ease-out"
          style={{ transform: showAlloc ? "translateY(0)" : "translateY(0)", opacity: 1 }}>
          <h2 className="text-lg font-light text-white mb-5">
            <span className="text-amber-400 font-medium">Собрать</span> пакет
          </h2>

          <div className="flex flex-wrap items-end gap-3 mb-6">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-gray-500 mb-1.5 font-mono">Сумма (₽)</label>
              <input
                type="number"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-lg font-mono text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/50 transition"
                min="500"
                step="100"
                placeholder="100000"
              />
            </div>
            <button
              onClick={fetchAllocation}
              disabled={loadingAlloc}
              className="px-8 py-3 rounded-xl font-medium text-sm transition-all duration-200 disabled:opacity-50"
              style={{ background: "linear-gradient(135deg, #F0B90B, #D4A107)", color: "#0B1A2F" }}
            >
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
                  <DonutChart plan={allocation.plan} reserve={allocation.reserve} capital={allocation.capital} />
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
                        <div
                          key={item.ticker}
                          className={`bg-white/[0.03] border border-white/5 rounded-xl p-3 pl-4 mb-1.5 border-l-4 ${catColors[key] || "border-l-gray-500"} hover:bg-white/[0.06] transition cursor-pointer`}
                          onClick={() => { setSelectedTicker(item.ticker); }}
                        >
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

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
              <div className="flex items-center gap-3 mb-4">
                <h2 className="text-sm font-light text-white">AI совет</h2>
                <input
                  list="tickers"
                  className="bg-white/5 border border-white/10 px-3 py-1.5 rounded-lg text-sm font-mono text-white flex-1 min-w-0 focus:outline-none focus:border-amber-400/50"
                  value={selectedTicker}
                  onChange={(e) => setSelectedTicker(e.target.value.toUpperCase())}
                />
                <datalist id="tickers">
                  {instruments.map((i) => <option key={i.id} value={i.ticker} />)}
                </datalist>
              </div>
              <pre className="text-xs whitespace-pre-wrap font-sans bg-white/[0.02] rounded-xl p-4 min-h-[80px] text-gray-300 leading-relaxed">
                {advice || "Загрузка..."}
              </pre>
            </section>

            {selectedInst && (
              <PriceChart ticker={selectedTicker} company={selectedInst.full_name || selectedTicker} />
            )}

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
                      <tr
                        key={i.id}
                        className="border-b border-white/5 hover:bg-white/[0.02] cursor-pointer transition"
                        onClick={() => setSelectedTicker(i.ticker)}
                      >
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
          </div>

          <aside className="space-y-5">
            {latestGeo && (
              <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
                <h3 className="text-sm font-light text-white mb-3">Геополитический риск</h3>
                <div className="flex items-center gap-3 mb-3">
                  <div className={`w-2.5 h-2.5 rounded-full ${latestGeo.score > 7 ? "bg-red-500" : latestGeo.score > 5 ? "bg-amber-400" : "bg-emerald-500"} animate-pulse`} />
                  <span className="text-3xl font-mono font-light text-white">{latestGeo.score.toFixed(1)}</span>
                  <span className="text-xs text-gray-600">/10</span>
                </div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${latestGeo.score > 7 ? "bg-red-500" : latestGeo.score > 5 ? "bg-amber-400" : "bg-emerald-500"}`}
                    style={{ width: `${latestGeo.score * 10}%` }}
                  />
                </div>
                {geoHistory.length > 1 && (
                  <div className="mt-4">
                    <p className="text-[10px] text-gray-600 mb-1.5">14 дней</p>
                    <div className="flex items-end gap-0.5 h-10">
                      {geoHistory.map((g, i) => (
                        <div
                          key={i}
                          className={`flex-1 rounded-t ${g.score > 7 ? "bg-red-500/40" : g.score > 5 ? "bg-amber-400/40" : "bg-emerald-500/40"}`}
                          style={{ height: `${g.score * 10}%` }}
                          title={`${g.date}: ${g.score.toFixed(1)}`}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
              <h3 className="text-sm font-light text-white mb-3">Последние новости</h3>
              <div className="space-y-2.5">
                {news.map((n) => (
                  <div key={n.id} className="border-b border-white/5 pb-2.5 last:border-0">
                    <a href={n.url} target="_blank" className="text-xs text-gray-300 hover:text-amber-400 transition line-clamp-2" rel="noreferrer">
                      {n.title}
                    </a>
                    <p className="text-[10px] text-gray-600 mt-1">{n.source} — {n.published_at?.slice(0, 10)}</p>
                  </div>
                ))}
                {news.length === 0 && <p className="text-xs text-gray-600">Новости не загружены</p>}
              </div>
            </div>

            <PortfolioSimulator />
          </aside>
        </div>
      </div>
      {showAuth && <AuthModal onClose={() => setShowAuth(false)} onAuth={(s) => { setAuth(s); setShowAuth(false); }} />}
      <style jsx global>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fadeIn { animation: fadeIn 0.5s ease-out; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
        input[type="number"]::-webkit-inner-spin-button { opacity: 0.3; }
      `}</style>
    </div>
  );
}
