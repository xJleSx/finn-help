export type Verdict = "strong_buy" | "buy" | "hold" | "reduce" | "sell";

export interface BondAnalysis {
  score: number;
  verdict: Verdict;
  pros: string[];
  cons: string[];
  risks: string[];
  allocation: number;
  updatedAt: string;
}
