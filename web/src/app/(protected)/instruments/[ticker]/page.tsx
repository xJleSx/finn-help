"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import { api } from "@/lib/api-client";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { CandlestickChart } from "@/components/CandlestickChart";
import { TradePlanCard } from "@/components/TradePlanCard";
import { SignalBadge } from "@/components/SignalBadge";

export default function InstrumentDetailPage({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);

  const { data: detail } = useQuery({
    queryKey: ["instrument", ticker],
    queryFn: () => api.instruments.detail(ticker),
  });

  const { data: signal } = useQuery({
    queryKey: ["signal", ticker],
    queryFn: () => api.instruments.signal(ticker),
    refetchInterval: 60_000,
  });

  const { data: tradePlan } = useQuery({
    queryKey: ["trade-plan", ticker],
    queryFn: () => api.instruments.tradePlan(ticker),
    refetchInterval: 60_000,
  });

  const { data: advice } = useQuery({
    queryKey: ["advice", ticker],
    queryFn: () => api.instruments.advice(ticker),
    refetchInterval: 120_000,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-light text-white flex items-center gap-3">
            {ticker}
            {detail && <span className="text-sm font-normal text-gray-500">{detail.full_name}</span>}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {detail?.sector || ""} {detail?.currency ? `· ${detail.currency}` : ""}
          </p>
        </div>
        {signal && <SignalBadge signal={signal as Record<string, unknown>} />}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <ErrorBoundary>
            <CandlestickChart ticker={ticker} />
          </ErrorBoundary>

          <ErrorBoundary>
            {tradePlan && <TradePlanCard plan={tradePlan} />}
          </ErrorBoundary>

          <ErrorBoundary>
            {advice && (
              <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
                <h2 className="text-sm font-light text-white mb-3">AI Анализ</h2>
                <pre className="text-xs whitespace-pre-wrap font-sans bg-white/[0.02] rounded-xl p-4 text-gray-300 leading-relaxed">
                  {advice.advice || JSON.stringify(advice.signal, null, 2)}
                </pre>
              </section>
            )}
          </ErrorBoundary>
        </div>

        <aside className="space-y-5">
          <ErrorBoundary>
            {signal && (
              <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
                <h2 className="text-sm font-light text-white mb-3">Сигнал</h2>
                {(() => {
                  const s = signal as Record<string, unknown>;
                  const fv = s.fused;
                  const cv = s.confidence;
                  const tv = s.technical;
                  const fuv = s.fundamental;
                  return (
                    <div className="space-y-2 text-xs">
                      {fv != null && (
                        <div className="flex items-center gap-2">
                          <span className="text-gray-500">Fused:</span>
                          <span className="font-mono text-white">{String(fv)}</span>
                        </div>
                      )}
                      {cv != null && (
                        <div>
                          <span className="text-gray-500">Уверенность:</span>
                          <div className="mt-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-amber-400 rounded-full"
                              style={{ width: `${Math.min((cv as number) * 100, 100)}%` }}
                            />
                          </div>
                          <span className="font-mono text-white text-[10px]">
                            {((cv as number) * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                      {tv != null && (
                        <div>
                          <span className="text-gray-500">Technical:</span>
                          <span className="font-mono text-white ml-1">{JSON.stringify(tv)}</span>
                        </div>
                      )}
                      {fuv != null && (
                        <div>
                          <span className="text-gray-500">Fundamental:</span>
                          <span className="font-mono text-white ml-1">{JSON.stringify(fuv)}</span>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </section>
            )}
          </ErrorBoundary>

          <ErrorBoundary>
            {signal && (() => {
              const s = signal as Record<string, unknown>;
              const ml = s.ml;
              if (!ml || typeof ml !== "object") return null;
              return (
                <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
                  <h2 className="text-sm font-light text-white mb-3">ML Прогнозы</h2>
                  <div className="space-y-2 text-xs">
                    {Object.entries(ml as Record<string, unknown>).map(([model, pred]) => (
                      <div key={model} className="bg-white/[0.03] rounded-lg p-2.5 border border-white/5">
                        <span className="text-gray-500">{model}:</span>
                        <span className="font-mono text-white ml-1">{String(pred)}</span>
                      </div>
                    ))}
                  </div>
                </section>
              );
            })()}
          </ErrorBoundary>
        </aside>
      </div>
    </div>
  );
}
