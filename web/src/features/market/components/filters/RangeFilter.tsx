"use client";

interface Props {
  label: string;
  min: number;
  max: number;
  valueMin: number;
  valueMax: number;
  onMinChange: (v: number) => void;
  onMaxChange: (v: number) => void;
  unit?: string;
  step?: number;
}

export default function RangeFilter({ label, min, max, valueMin, valueMax, onMinChange, onMaxChange, unit = "", step = 0.1 }: Props) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={valueMin}
          onChange={(e) => onMinChange(Number(e.target.value))}
          min={min}
          max={max}
          step={step}
          className="h-8 w-20 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:border-primary focus:outline-none"
        />
        <span className="text-xs text-muted-foreground">—</span>
        <input
          type="number"
          value={valueMax}
          onChange={(e) => onMaxChange(Number(e.target.value))}
          min={min}
          max={max}
          step={step}
          className="h-8 w-20 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:border-primary focus:outline-none"
        />
        {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
      </div>
    </div>
  );
}
