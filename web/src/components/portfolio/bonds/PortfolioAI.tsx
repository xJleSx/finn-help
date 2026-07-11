import Section from "@/components/bonds/details/AIAnalysisCard/Section";

export interface PortfolioAIProps {
  risk: string;
  diversification: number;
  avgRating: string;
  recommendation: string;
  expectedReturn: number;
}

export default function PortfolioAI({ risk, diversification, avgRating, recommendation, expectedReturn }: PortfolioAIProps) {
  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        AI Summary
      </h3>

      <div className="space-y-4">
        <div className="flex items-center justify-between border-b border-border/50 pb-3">
          <span className="text-sm text-muted-foreground">Риск</span>
          <span className={`text-sm font-semibold ${
            risk === "Низкий" ? "text-emerald-500" : risk === "Средний" ? "text-yellow-500" : "text-red-500"
          }`}>
            {risk}
          </span>
        </div>

        <div className="flex items-center justify-between border-b border-border/50 pb-3">
          <span className="text-sm text-muted-foreground">Диверсификация</span>
          <span className="text-sm font-semibold tabular-nums text-foreground">{diversification}%</span>
        </div>

        <div className="flex items-center justify-between border-b border-border/50 pb-3">
          <span className="text-sm text-muted-foreground">Средний рейтинг</span>
          <span className="text-sm font-semibold text-foreground">{avgRating}</span>
        </div>

        <Section title="Рекомендация">
          <p className="text-sm text-muted-foreground">{recommendation}</p>
        </Section>

        <div className="flex items-center justify-between rounded-lg bg-primary/5 p-3">
          <span className="text-sm text-muted-foreground">Ожидаемая доходность</span>
          <span className="text-lg font-bold tabular-nums text-foreground">
            {expectedReturn.toFixed(1)}%
          </span>
        </div>
      </div>
    </div>
  );
}
