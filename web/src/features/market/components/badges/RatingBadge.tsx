interface Props {
  rating: string;
}

const COLORS: Record<string, string> = {
  AAA: "bg-emerald-500/15 text-emerald-500",
  "AA+": "bg-green-500/15 text-green-500",
  AA: "bg-lime-500/15 text-lime-500",
  "AA-": "bg-lime-400/15 text-lime-400",
  "A+": "bg-yellow-500/15 text-yellow-500",
  A: "bg-yellow-500/15 text-yellow-500",
  "A-": "bg-yellow-400/15 text-yellow-400",
  "BBB+": "bg-orange-500/15 text-orange-500",
  BBB: "bg-orange-500/15 text-orange-500",
  "BBB-": "bg-orange-400/15 text-orange-400",
  "BB+": "bg-red-500/15 text-red-500",
  BB: "bg-red-500/15 text-red-500",
  NR: "bg-gray-500/15 text-gray-500",
};

export default function RatingBadge({ rating }: Props) {
  const color = COLORS[rating] ?? COLORS.NR;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${color}`}>
      {rating}
    </span>
  );
}
