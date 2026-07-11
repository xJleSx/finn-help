export type AISignal = "strong_buy" | "buy" | "hold" | "weak" | "sell";

export interface AIScoreInfo {
  label: string;
  signal: AISignal;
  color: string;
  barColor: string;
}

export function getAIScoreInfo(score: number): AIScoreInfo {
  if (score >= 95) return { label: "Strong Buy", signal: "strong_buy", color: "text-emerald-500", barColor: "bg-emerald-500" };
  if (score >= 80) return { label: "Buy", signal: "buy", color: "text-green-500", barColor: "bg-green-500" };
  if (score >= 65) return { label: "Hold", signal: "hold", color: "text-yellow-500", barColor: "bg-yellow-500" };
  if (score >= 50) return { label: "Weak", signal: "weak", color: "text-orange-500", barColor: "bg-orange-500" };
  return { label: "Sell", signal: "sell", color: "text-red-500", barColor: "bg-red-500" };
}
