import type { AIAnalysis } from "@/types/ai-analysis";
import Section from "./Section";
import OpportunityItem from "./OpportunityItem";
import RiskItem from "./RiskItem";
import Recommendation from "./Recommendation";

interface Props {
  analysis: AIAnalysis;
}

export default function AIAnalysisCard({ analysis }: Props) {
  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        AI Анализ
      </h3>

      <div className="space-y-5">
        <p className="text-sm leading-relaxed text-muted-foreground">{analysis.summary}</p>

        <Section title="Что понравилось AI" icon="✔">
          <div className="space-y-2">
            {analysis.strengths.map((s, i) => (
              <OpportunityItem key={i} text={s} />
            ))}
          </div>
        </Section>

        <Section title="Основные риски" icon="⚠">
          <div className="space-y-2">
            {analysis.risks.map((r, i) => (
              <RiskItem key={i} text={r} />
            ))}
          </div>
        </Section>

        <div className="h-px bg-border/50" />

        <Recommendation
          recommendation={analysis.recommendation}
          investmentHorizon={analysis.investmentHorizon}
          confidence={analysis.confidence}
        />
      </div>
    </div>
  );
}
