export interface BondPortfolioSummary {
  totalValue: number;
  totalProfit: number;
  totalReturn: number;
  avgYtm: number;
  avgAiScore: number;
}

export interface ScenarioBPlan {
  scenarioBActive: boolean;
  triggerReason: string;
  currentDuration: number;
  targetDuration: number;
  sellRecommendations: { ticker: string; duration: number; reason: string }[];
  buyRecommendations: { ticker: string; type: string; reason: string; suggestedPct: number }[];
  actions: string[];
  totalSellPct: number;
  totalBuyPct: number;
}

export interface RebalancingInfo {
  activeTriggers: { trigger: string; severity: string; message: string }[];
  triggerCount: number;
  recommendations: string[];
  severityCount: { high: number; medium: number; low: number; info: number };
}

export interface MacroScenario {
  selectedScenario: string;
  score: number;
  rating: string;
  keyRate: number;
  inflation: number;
  details: string;
}

export interface InflationForecast {
  inflationForecast: number;
  officialCPI: number | null;
  keyRate: number | null;
  realKeyRate: number | null;
}

export interface BondPortfolioResponse {
  positions: import("./bond-position").BondPosition[];
  summary: BondPortfolioSummary;
  allocation: { recommended: { label: string; value: number }[]; actual: { label: string; value: number }[] };
  defaultImpact: Record<string, unknown>;
  rateCycle: Record<string, unknown>;
  scenarioB: ScenarioBPlan;
  rebalancing: RebalancingInfo;
  macroScenario: MacroScenario;
  inflationForecast: InflationForecast;
  ladder: { year: number; ticker: string; value: number; ytm: number; rating: string }[];
  healthScore: number;
  warnings: string[];
  ratingDistribution: Record<string, number>;
  portfolioOptimization: Record<string, unknown>;
}
