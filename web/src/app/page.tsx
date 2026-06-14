"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type Instrument = {
  id: number;
  ticker: string;
  full_name: string;
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
  existing_portfolio: { ticker: string; quantity: number; avg_price: number; current_value: number }[];
};

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [news, setNews] = useState<News[]>([]);
  const [geoHistory, setGeoHistory] = useState<GeoRisk[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string>("SBER");
  const [advice, setAdvice] = useState<string>("");

  const [capital, setCapital] = useState<string>("100000");
  const [allocation, setAllocation] = useState<AllocationPlan | null>(null);
  const [loadingAlloc, setLoadingAlloc] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [instRes, newsRes, geoRes] = await Promise.all([
          fetch(`${API}/api/instruments`),
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
      return () => es.close();
    };

    fetchData();
    const cleanup = fetchEvents();
    return cleanup;
  }, []);

  const fetchAdvice = async (ticker: string) => {
    try {
      const res = await fetch(`${API}/api/instruments/${ticker}/advice`);
      if (!res.ok) return;
      const data = await res.json();
      setAdvice(data.advice || JSON.stringify(data.signal, null, 2));
    } catch {
      setAdvice("API недоступен. Запустите: uv run finn");
    }
  };

  useEffect(() => {
    fetchAdvice(selectedTicker);
  }, [selectedTicker]);

  const fetchAllocation = async () => {
    setLoadingAlloc(true);
    try {
      const val = Math.max(500, parseFloat(capital) || 50000);
      const res = await fetch(`${API}/api/portfolio/allocate?capital=${val}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(await res.text());
      setAllocation(await res.json());
      setCapital(String(val));
    } catch (e) {
      console.error("Allocation failed", e);
    } finally {
      setLoadingAlloc(false);
    }
  };

  const latestGeo = geoHistory[geoHistory.length - 1];

  const formatCurrency = (v: number) =>
    v.toLocaleString("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0, maximumFractionDigits: 0 });

  const catColors: Record<string, string> = {
    etf: "bg-blue-500",
    dividend: "bg-emerald-500",
    bond: "bg-amber-500",
    growth: "bg-violet-500",
  };

  return (
    <main className="p-6 max-w-6xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold">FinAdvisor</h1>
        <p className="text-gray-400">AI финансовый ассистент для MOEX</p>
        {dashboard && (
          <div className="flex gap-6 mt-2 text-sm text-gray-500">
            <span>Инструментов: {dashboard.instruments}</span>
            <span>Сигналов: {dashboard.signals}</span>
            {latestGeo && (
              <span className={latestGeo.score > 7 ? "text-red-400" : latestGeo.score > 5 ? "text-yellow-400" : "text-green-400"}>
                GeoRisk: {latestGeo.score.toFixed(1)}/10
              </span>
            )}
          </div>
        )}
      </header>

      <section className="bg-gray-900 rounded-xl p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">📊 Распределение портфеля</h2>

        <div className="flex flex-wrap items-end gap-4 mb-6">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-sm text-gray-400 mb-1">Капитал для инвестиций (₽)</label>
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
              className="w-full bg-gray-800 px-4 py-2 rounded-lg text-lg"
              min="500"
              step="1000"
            />
          </div>
          <button
            onClick={fetchAllocation}
            disabled={loadingAlloc}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 px-6 py-2 rounded-lg font-medium transition"
          >
            {loadingAlloc ? "Расчёт..." : "Рассчитать"}
          </button>
        </div>

        {allocation && (
          <div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
              <div className="bg-gray-800 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-400">Капитал</p>
                <p className="text-lg font-bold">{formatCurrency(allocation.capital)}</p>
              </div>
              <div className="bg-gray-800 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-400">Распределено</p>
                <p className="text-lg font-bold text-emerald-400">{formatCurrency(allocation.total_allocated)}</p>
              </div>
              <div className="bg-gray-800 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-400">Резерв</p>
                <p className="text-lg font-bold text-amber-400">{formatCurrency(allocation.reserve)}</p>
              </div>
              <div className="bg-gray-800 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-400">Доходность/мес</p>
                <p className="text-lg font-bold text-emerald-400">
                  {allocation.projected_monthly_yield > 0
                    ? `${formatCurrency(allocation.projected_monthly_yield)}`
                    : "—"}
                </p>
              </div>
            </div>

            <div className="flex gap-1 mb-6 h-3 rounded-full overflow-hidden">
              {Object.entries(allocation.plan).map(([key, cat]) => {
                const pct = (cat.budget / allocation.capital) * 100;
                return (
                  <div
                    key={key}
                    className={`${catColors[key] || "bg-gray-500"} transition-all`}
                    style={{ width: `${pct}%` }}
                    title={`${cat.label}: ${pct.toFixed(0)}%`}
                  />
                );
              })}
              {allocation.reserve > 0 && (
                <div
                  className="bg-gray-700 transition-all"
                  style={{ width: `${(allocation.reserve / allocation.capital) * 100}%` }}
                  title={`Резерв: ${((allocation.reserve / allocation.capital) * 100).toFixed(0)}%`}
                />
              )}
            </div>

            <div className="space-y-4">
              {Object.entries(allocation.plan).map(([key, cat]) => (
                <div key={key}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className={`w-3 h-3 rounded-full ${catColors[key] || "bg-gray-500"}`} />
                    <h3 className="font-semibold">{cat.label}</h3>
                    <span className="text-sm text-gray-400">— {formatCurrency(cat.budget)}</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-gray-400 border-b border-gray-800">
                          <th className="text-left py-1">Тикер</th>
                          <th className="text-left py-1">Название</th>
                          <th className="text-right py-1">Сумма</th>
                          <th className="text-left py-1 hidden sm:table-cell">Обоснование</th>
                          <th className="text-right py-1 hidden md:table-cell">Доходность</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cat.items.map((item) => (
                          <tr key={item.ticker} className="border-b border-gray-800/30">
                            <td className="py-2 font-mono text-blue-400">{item.ticker}</td>
                            <td className="py-2">{item.name}</td>
                            <td className="py-2 text-right font-mono">{formatCurrency(item.amount)}</td>
                            <td className="py-2 text-gray-400 text-xs hidden sm:table-cell">{item.reason}</td>
                            <td className="py-2 text-right hidden md:table-cell">
                              {item.expected_yield > 0 ? `${item.expected_yield.toFixed(1)}%` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>

            {allocation.existing_portfolio.length > 0 && (
              <div className="mt-6 p-4 bg-gray-800/50 rounded-lg">
                <h3 className="font-semibold mb-2">Текущий портфель</h3>
                <div className="text-sm text-gray-400">
                  {allocation.existing_portfolio.map((p) => (
                    <span key={p.ticker} className="mr-4">
                      {p.ticker}: {p.quantity} шт. ({formatCurrency(p.current_value)})
                    </span>
                  ))}
                </div>
              </div>
            )}

            <p className="text-xs text-gray-500 mt-4">
              * Консервативное распределение: 40% БПИФ, 30% дивидендные акции, 20% облигации, 10% акции роста.
              Целевая доходность ~10% годовых (0.8% в месяц).
            </p>
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2">
          <div className="bg-gray-900 rounded-xl p-4 mb-4">
            <div className="flex items-center gap-3 mb-4">
              <h2 className="text-xl font-semibold">Совет AI</h2>
              <input
                list="tickers"
                className="bg-gray-800 px-3 py-1 rounded text-sm flex-1"
                value={selectedTicker}
                onChange={(e) => setSelectedTicker(e.target.value.toUpperCase())}
              />
              <datalist id="tickers">
                {instruments.map((i) => (
                  <option key={i.id} value={i.ticker} />
                ))}
              </datalist>
            </div>
            <pre className="text-sm whitespace-pre-wrap font-sans bg-gray-800 p-4 rounded-lg min-h-[100px]">
              {advice || "Загрузка..."}
            </pre>
          </div>

          <div className="bg-gray-900 rounded-xl p-4">
            <h2 className="text-xl font-semibold mb-3">Инструменты</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 border-b border-gray-800">
                    <th className="text-left py-2">Тикер</th>
                    <th className="text-left py-2">Название</th>
                    <th className="text-right py-2">Цена</th>
                  </tr>
                </thead>
                <tbody>
                  {instruments.slice(0, 20).map((i) => (
                    <tr key={i.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                      onClick={() => setSelectedTicker(i.ticker)}>
                      <td className="py-2 font-mono text-blue-400">{i.ticker}</td>
                      <td className="py-2">{i.full_name}</td>
                      <td className="py-2 text-right">
                        {i.last_price !== null ? `${i.last_price.toFixed(2)} ₽` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <aside className="space-y-4">
          {latestGeo && (
            <div className="bg-gray-900 rounded-xl p-4">
              <h3 className="font-semibold mb-2">Геополитический риск</h3>
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded-full ${latestGeo.score > 7 ? "bg-red-500" : latestGeo.score > 5 ? "bg-yellow-500" : "bg-green-500"}`} />
                <span className="text-2xl font-bold">{latestGeo.score.toFixed(1)}</span>
                <span className="text-gray-400">/10</span>
              </div>
              <div className="mt-2 h-2 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${latestGeo.score > 7 ? "bg-red-500" : latestGeo.score > 5 ? "bg-yellow-500" : "bg-green-500"}`}
                  style={{ width: `${latestGeo.score * 10}%` }}
                />
              </div>
              {geoHistory.length > 1 && (
                <div className="mt-3">
                  <p className="text-xs text-gray-500 mb-1">История (14 дней)</p>
                  <div className="flex items-end gap-1 h-12">
                    {geoHistory.map((g, i) => (
                      <div
                        key={i}
                        className={`flex-1 rounded-t ${g.score > 7 ? "bg-red-500/60" : g.score > 5 ? "bg-yellow-500/60" : "bg-green-500/60"}`}
                        style={{ height: `${g.score * 10}%` }}
                        title={`${g.date}: ${g.score.toFixed(1)}`}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="bg-gray-900 rounded-xl p-4">
            <h3 className="font-semibold mb-2">Последние новости</h3>
            <div className="space-y-2">
              {news.map((n) => (
                <div key={n.id} className="text-sm border-b border-gray-800 pb-2">
                  <a href={n.url} target="_blank" className="text-blue-400 hover:text-blue-300 line-clamp-2" rel="noreferrer">
                    {n.title}
                  </a>
                  <p className="text-gray-500 text-xs mt-1">{n.source} — {n.published_at?.slice(0, 10)}</p>
                </div>
              ))}
              {news.length === 0 && <p className="text-gray-500 text-sm">Новости не загружены</p>}
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
