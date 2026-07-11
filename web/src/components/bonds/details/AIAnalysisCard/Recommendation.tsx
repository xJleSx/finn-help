import AIScore from "@/components/market/cells/AIScore";

interface Props {
  recommendation: string;
  investmentHorizon: string;
  confidence: number;
}

export default function Recommendation({ recommendation, investmentHorizon, confidence }: Props) {
  return (
    <div className="flex items-center justify-between rounded-lg border bg-card/50 p-4">
      <div className="space-y-1">
        <div className="text-xs text-muted-foreground">Итог</div>
        <div className="text-lg font-bold text-foreground">{recommendation}</div>
        <div className="text-xs text-muted-foreground">Горизонт: {investmentHorizon}</div>
      </div>
      <div className="text-right">
        <div className="text-xs text-muted-foreground">Уверенность AI</div>
        <AIScore score={confidence} />
      </div>
    </div>
  );
}
