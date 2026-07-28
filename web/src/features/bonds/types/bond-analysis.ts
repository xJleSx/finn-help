export type Verdict = "strong_buy" | "buy" | "hold" | "reduce" | "sell";

export interface RateCycleAdvice {
  phase: string;
  label: string;
  description: string;
  confidence?: number;
  ruoniaSpreadBps?: number;
  ofzShortYield?: number;
  cbrRhetoric?: string;
  recommendation: Record<string, unknown>;
  bondFit: string;
}

export interface DefaultImpact {
  positionSeverity: string;
  positionValue: number;
  portfolioValue: number;
  rating: string;
  ytm: number;
  potentialLoss: number;
  lossPct: number;
}

export interface AfterTaxYield {
  ytmGross: number;
  ytmAfterCouponTax: number;
  ytmAfterCosts: number;
  realYield: number | null;
  inflationForecast: number | null;
  brokerCommissionPct: number;
  ldvEligible: boolean;
}

export interface LiquidityInfo {
  liquidityScore: string;
  liquidityPct: number;
  warnings: string[];
}

export interface PutOptionInfo {
  hasPut: boolean;
  putValue: number;
  protectionPct: number;
}

export interface KellySizer {
  kellyFraction: number;
  cappedFraction: number;
  suggestedAmount: number;
  notes: string[];
}

export interface LDVInfo {
  ldvEligible: boolean;
  reasons: string[];
}

export interface SpreadInfo {
  spreadPct: number;
  maxAcceptable: number;
}

export interface RealYieldChain {
  ytmGross: number;
  realYield: number | null;
  chain: { step: string; value: number | null; delta: number | null }[];
}

export interface PortfolioContext {
  recommendedAllocationPct: number;
  investmentHorizon: string;
  suitableForSmallPortfolio: string;
  rateCycleFit: string;
}

export interface BondAnalysis {
  score: number;
  verdict: Verdict;
  pros: string[];
  cons: string[];
  risks: string[];
  allocation: number;
  updatedAt: string;
  rateCycleAdvice?: RateCycleAdvice;
  defaultImpact?: DefaultImpact;
  afterTaxYield?: AfterTaxYield;
  liquidity?: LiquidityInfo;
  realYield?: RealYieldChain;
  putOption?: PutOptionInfo;
  kellySizer?: KellySizer;
  ldvEligibility?: LDVInfo;
  spreadInfo?: SpreadInfo;
  portfolioContext?: PortfolioContext;
}
