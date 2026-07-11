import { getAIScoreInfo } from "@/lib/market/aiScore";

interface Props {
  score: number;
}

const BAR_SEGMENTS = 12;

export default function AIScore({ score }: Props) {
  const info = getAIScoreInfo(score);
  const filled = Math.round((score / 100) * BAR_SEGMENTS);

  return (
    <div className="flex items-center gap-2 min-w-[140px]">
      <div className="flex gap-0.5">
        {Array.from({ length: BAR_SEGMENTS }).map((_, i) => (
          <span
            key={i}
            className={`block h-4 w-2 rounded-sm transition-colors duration-300 ${
              i < filled ? info.barColor : "bg-muted"
            }`}
          />
        ))}
      </div>
      <span className={`text-xs font-semibold ${info.color}`}>{score}</span>
    </div>
  );
}
