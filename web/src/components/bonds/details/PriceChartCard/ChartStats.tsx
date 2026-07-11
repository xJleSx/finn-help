import { TrendingUp, TrendingDown, BarChart3, Minus, ArrowUpDown } from "lucide-react";
import { formatCurrency } from "@/lib/format";

interface Stats {
  currentPrice: number;
  change: number;
  high: number;
  low: number;
  volume: number;
}

interface Props {
  stats: Stats;
}

function StatItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{icon}</span>
      <div className="flex items-baseline gap-1.5">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums text-foreground">{value}</span>
      </div>
    </div>
  );
}

export default function ChartStats({ stats }: Props) {
  const changePositive = stats.change >= 0;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
      <StatItem
        icon={changePositive ? <TrendingUp className="h-4 w-4 text-emerald-500" /> : <TrendingDown className="h-4 w-4 text-red-500" />}
        label="Цена"
        value={formatCurrency(stats.currentPrice)}
      />
      <div className={`flex items-center gap-1 text-sm font-semibold tabular-nums ${
        changePositive ? "text-emerald-500" : "text-red-500"
      }`}>
        {changePositive ? "+" : ""}{stats.change.toFixed(2)}%
      </div>
      <StatItem icon={<Minus className="h-4 w-4 text-muted-foreground" />} label="Макс" value={formatCurrency(stats.high)} />
      <StatItem icon={<Minus className="h-4 w-4 text-muted-foreground" />} label="Мин" value={formatCurrency(stats.low)} />
      <StatItem icon={<BarChart3 className="h-4 w-4 text-muted-foreground" />} label="Объём" value={formatCurrency(stats.volume)} />
    </div>
  );
}
