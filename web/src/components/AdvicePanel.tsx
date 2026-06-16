"use client";

import { useEffect, useRef, useState } from "react";
import type { Instrument } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function AdvicePanel({ selectedTicker, onSelectTicker, instruments }: {
  selectedTicker: string; onSelectTicker: (t: string) => void; instruments: Instrument[];
}) {
  const [advice, setAdvice] = useState<string>("");
  const fetchedRef = useRef("");

  useEffect(() => {
    if (fetchedRef.current === selectedTicker) return;
    fetchedRef.current = selectedTicker;
    fetch(`${API}/api/instruments/${selectedTicker}/advice`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((data) => setAdvice(data.advice || JSON.stringify(data.signal, null, 2)))
      .catch(() => setAdvice("API недоступен"));
  }, [selectedTicker]);

  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-sm font-light text-white">AI совет</h2>
        <input list="tickers"
          className="bg-white/5 border border-white/10 px-3 py-1.5 rounded-lg text-sm font-mono text-white flex-1 min-w-0 focus:outline-none focus:border-amber-400/50"
          value={selectedTicker} onChange={(e) => onSelectTicker(e.target.value.toUpperCase())} />
        <datalist id="tickers">
          {instruments.map((i) => <option key={i.id} value={i.ticker} />)}
        </datalist>
      </div>
      <pre className="text-xs whitespace-pre-wrap font-sans bg-white/[0.02] rounded-xl p-4 min-h-[80px] text-gray-300 leading-relaxed">
        {advice || "Загрузка..."}
      </pre>
    </section>
  );
}
