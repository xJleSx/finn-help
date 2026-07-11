import type { Verdict } from "@/types/bond-analysis";

interface Props {
  verdict: Verdict;
}

const LABELS: Record<Verdict, string> = {
  strong_buy: "Strong Buy",
  buy: "Buy",
  hold: "Hold",
  reduce: "Reduce",
  sell: "Sell",
};

const COLORS: Record<Verdict, string> = {
  strong_buy: "bg-emerald-500/15 text-emerald-500",
  buy: "bg-green-500/15 text-green-500",
  hold: "bg-yellow-500/15 text-yellow-500",
  reduce: "bg-orange-500/15 text-orange-500",
  sell: "bg-red-500/15 text-red-500",
};

export default function VerdictBadge({ verdict }: Props) {
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${COLORS[verdict]}`}>
      {LABELS[verdict]}
    </span>
  );
}
