const RATING_COLORS: Record<string, string> = {
  AAA: "bg-emerald-500",
  "AA+": "bg-green-500",
  AA: "bg-lime-500",
  "AA-": "bg-lime-400",
  "A+": "bg-yellow-500",
  A: "bg-yellow-500",
  "A-": "bg-yellow-400",
  "BBB+": "bg-orange-500",
  BBB: "bg-orange-500",
  "BBB-": "bg-orange-400",
  "BB+": "bg-red-500",
  BB: "bg-red-500",
  NR: "bg-gray-500",
};

export function getRatingColor(rating: string): string {
  return RATING_COLORS[rating] ?? "bg-gray-500";
}

export function getRatingScore(rating: string): number {
  const order = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "NR"];
  const idx = order.indexOf(rating);
  return idx === -1 ? 12 : idx;
}
