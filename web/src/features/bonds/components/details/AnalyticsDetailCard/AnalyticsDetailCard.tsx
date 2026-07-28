import type { BondAnalysis } from "@/features/bonds/types/bond-analysis";

interface Props {
  analysis: BondAnalysis;
}

export default function AnalyticsDetailCard({ analysis }: Props) {
  const { afterTaxYield, liquidity, realYield, putOption, kellySizer, ldvEligibility, spreadInfo, rateCycleAdvice } = analysis;

  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Расширенный анализ
      </h3>
      <div className="space-y-5">
        {afterTaxYield && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Доходность после налогов</p>
            <div className="space-y-1 text-sm">
              <Row label="YTM (gross)" value={`${afterTaxYield.ytmGross.toFixed(2)}%`} />
              <Row label="После налога на купон" value={`${afterTaxYield.ytmAfterCouponTax.toFixed(2)}%`} />
              <Row label="После комиссий" value={`${afterTaxYield.ytmAfterCosts.toFixed(2)}%`} />
              {afterTaxYield.realYield !== null && (
                <Row label="Реальная доходность" value={`${afterTaxYield.realYield.toFixed(2)}%`} highlight />
              )}
              {afterTaxYield.inflationForecast !== null && (
                <Row label="Прогноз инфляции" value={`${afterTaxYield.inflationForecast.toFixed(1)}%`} />
              )}
            </div>
          </div>
        )}

        {liquidity && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Ликвидность</p>
            <div className="space-y-1 text-sm">
              <Row
                label="Уровень"
                value={liquidity.liquidityScore === "high" ? "Высокая" : liquidity.liquidityScore === "medium" ? "Средняя" : "Низкая"}
                highlight={liquidity.liquidityScore === "high"}
              />
              <Row label="Оценка" value={`${liquidity.liquidityPct}%`} />
              {liquidity.warnings.length > 0 && (
                <p className="mt-1 text-xs text-red-500">{liquidity.warnings[0]}</p>
              )}
            </div>
          </div>
        )}

        {putOption && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Пут-опцион</p>
            <div className="space-y-1 text-sm">
              {putOption.hasPut ? (
                <>
                  <Row label="Защита" value={`${putOption.putValue.toFixed(2)} ₽`} />
                  <Row label="В % от цены" value={`${putOption.protectionPct.toFixed(1)}%`} />
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Оферта отсутствует</p>
              )}
            </div>
          </div>
        )}

        {kellySizer && kellySizer.cappedFraction > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Kelly Sizer</p>
            <div className="space-y-1 text-sm">
              <Row label="Доля портфеля" value={`${(kellySizer.cappedFraction * 100).toFixed(1)}%`} />
              <Row label="Сумма" value={`${kellySizer.suggestedAmount.toFixed(0)} ₽`} />
            </div>
          </div>
        )}

        {ldvEligibility && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">ЛДВ</p>
            <p className="text-sm">{ldvEligibility.ldvEligible ? "✅ Применима" : "❌ Не применима"}</p>
            {ldvEligibility.reasons.map((r, i) => (
              <p key={i} className="text-xs text-muted-foreground">{r}</p>
            ))}
          </div>
        )}

        {spreadInfo && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Спред</p>
            <Row label="Bid-ask спред" value={`${spreadInfo.spreadPct.toFixed(2)}%`} />
          </div>
        )}

        {realYield && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Цепочка доходности</p>
            <div className="space-y-1 text-sm">
              {realYield.chain.map((c, i) => c.value !== null && c.delta !== null && (
                <Row key={i} label={c.step} value={`${c.value.toFixed(2)}%`} />
              ))}
              {realYield.realYield !== null && (
                <Row label="Итого реальная" value={`${realYield.realYield.toFixed(2)}%`} highlight />
              )}
            </div>
          </div>
        )}

        {rateCycleAdvice && (
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Цикл ставки</p>
            <div className="space-y-1 text-sm">
              <Row label="Фаза" value={rateCycleAdvice.label} />
              <Row label="Fit" value={rateCycleAdvice.bondFit} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-semibold tabular-nums ${highlight ? "text-primary" : "text-foreground"}`}>
        {value}
      </span>
    </div>
  );
}
