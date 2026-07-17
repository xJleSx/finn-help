interface Props {
  amount: number;
  percent: number;
}

export default function Profit({ amount, percent }: Props) {
  const positive = amount >= 0;

  return (
    <div className={`flex items-center gap-1.5 font-semibold tabular-nums ${positive ? "text-emerald-500" : "text-red-500"}`}>
      <span className="text-xs">{positive ? "▲" : "▼"}</span>
      <span>{positive ? "+" : ""}{amount.toLocaleString()} ₽</span>
      <span className="text-xs opacity-70">
        ({positive ? "+" : ""}{percent.toFixed(1)}%)
      </span>
    </div>
  );
}
