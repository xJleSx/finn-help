"use client";

import { useEffect, useState } from "react";

import type { AuthState, DashboardData, GeoRisk, Instrument, News } from "../components/types";
import AuthModal from "../components/AuthModal";
import AdvicePanel from "../components/AdvicePanel";
import PriceChart from "../components/PriceChart";
import SectorHeatmap from "../components/SectorHeatmap";
import InstrumentTable from "../components/InstrumentTable";
import AllocationSection from "../components/AllocationSection";
import GeoRiskPanel from "../components/GeoRiskPanel";
import NewsPanel from "../components/NewsPanel";
import PortfolioSimulator from "../components/PortfolioSimulator";
import MacroPanel from "../components/MacroPanel";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const AUTH_KEY = "finn_auth";

function loadAuth(): AuthState {
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { token: null, user: null };
}

function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [news, setNews] = useState<News[]>([]);
  const [geoHistory, setGeoHistory] = useState<GeoRisk[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string>("SBER");

  const [auth, setAuth] = useState<AuthState>({ token: null, user: null });
  const [showAuth, setShowAuth] = useState(false);

  useEffect(() => {
    const saved = loadAuth();
    if (saved.token) setAuth(saved);
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [instRes, newsRes, geoRes, macroRes] = await Promise.all([
          fetch(`${API}/api/instruments?type=stock`),
          fetch(`${API}/api/news?limit=5`),
          fetch(`${API}/api/geo-risk?days=14`),
          fetch(`${API}/api/macro`).catch(() => null),
        ]);
        setInstruments(await instRes.json());
        setNews(await newsRes.json());
        setGeoHistory(await geoRes.json());
        if (macroRes?.ok) {
          const m = await macroRes.json();
          const el = (id: string, v: string) => { const e = document.getElementById(id); if (e) e.textContent = v; };
          el("macro-brent", m.brent?.toFixed(1) ?? "—");
          el("macro-usd", m.usd_rate?.toFixed(2) ?? "—");
          el("macro-imoex", m.imoex?.toFixed(0) ?? "—");
          el("macro-rate", m.key_rate != null ? `${m.key_rate}%` : "—");
          el("macro-cpi", m.cpi != null ? `${m.cpi}%` : "—");
        }
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

  const latestGeo = geoHistory[geoHistory.length - 1];
  const selectedInst = instruments.find((i) => i.ticker === selectedTicker);

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

        <AllocationSection onSelectTicker={setSelectedTicker} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <AdvicePanel selectedTicker={selectedTicker} onSelectTicker={setSelectedTicker} instruments={instruments} />

            {selectedInst && (
              <PriceChart ticker={selectedTicker} company={selectedInst.full_name || selectedTicker} />
            )}

            <SectorHeatmap />

            <InstrumentTable instruments={instruments} onSelectTicker={setSelectedTicker} />
          </div>

          <aside className="space-y-5">
            <GeoRiskPanel geoHistory={geoHistory} />
            <NewsPanel news={news} />
            <PortfolioSimulator />
            <MacroPanel />
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
