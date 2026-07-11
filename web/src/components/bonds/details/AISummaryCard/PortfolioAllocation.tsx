interface Props {
  allocation: number;
}

export default function PortfolioAllocation({ allocation }: Props) {
  const clamped = Math.min(Math.max(allocation, 0), 100);
  const segments = 20;
  const filled = Math.round((clamped / 100) * segments);

  return (
    <div>
      <div className="mb-2 text-sm font-medium text-foreground">Рекомендуемая доля</div>
      <div className="flex items-center gap-3">
        <div className="flex gap-0.5 flex-1">
          {Array.from({ length: segments }).map((_, i) => (
            <span
              key={i}
              className={`block h-3 flex-1 rounded-sm ${
                i < filled ? "bg-primary" : "bg-muted"
              }`}
            />
          ))}
        </div>
        <span className="text-sm font-semibold tabular-nums">{clamped}%</span>
      </div>
    </div>
  );
}
