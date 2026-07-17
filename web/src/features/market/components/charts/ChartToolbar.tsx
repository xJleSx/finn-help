export const CHART_RANGES = ["1D", "5D", "1M", "3M", "6M", "1Y", "3Y", "ALL"] as const;
export type ChartRange = typeof CHART_RANGES[number];

interface Props {
  selected: ChartRange;
  onChange: (range: ChartRange) => void;
}

export default function ChartToolbar({ selected, onChange }: Props) {
  return (
    <div className="flex items-center gap-1">
      {CHART_RANGES.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onChange(r)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
            selected === r
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          }`}
        >
          {r}
        </button>
      ))}
    </div>
  );
}
