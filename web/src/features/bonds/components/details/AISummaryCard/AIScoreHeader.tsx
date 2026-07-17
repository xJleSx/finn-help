import AIScore from "@/features/market/components/cells/AIScore";

interface Props {
  name: string;
  ticker: string;
  score: number;
}

export default function AIScoreHeader({ name, ticker, score }: Props) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <div className="text-lg font-semibold text-foreground">{name}</div>
        <div className="text-sm text-muted-foreground">{ticker}</div>
      </div>
      <AIScore score={score} />
    </div>
  );
}
