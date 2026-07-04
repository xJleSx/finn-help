export type Instrument = {
  id: number;
  ticker: string;
  full_name: string;
  type: string;
  last_price: number | null;
  last_date: string | null;
};

export type InstrumentDetail = {
  id: number;
  ticker: string;
  full_name: string;
  isin: string | null;
  sector: string | null;
  type: string;
  lot_size: number | null;
  currency: string | null;
};

export type PriceData = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};

export type IndicatorData = {
  date: string;
  rsi: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  bb_upper: number | null;
  bb_lower: number | null;
  bb_mid: number | null;
  volume_sma_20: number | null;
  atr: number | null;
};

export type News = {
  id: number;
  title: string;
  summary: string | null;
  source: string;
  url: string;
  published_at: string | null;
};

export type GeoRisk = {
  date: string;
  score: number;
  components: Record<string, unknown> | null;
};

export type DashboardData = {
  instruments: number;
  signals: number;
  last_update: string | null;
  timestamp: string;
};

export type AllocationItem = {
  ticker: string;
  name: string;
  amount: number;
  reason: string;
  expected_yield: number;
};

export type AllocationCategory = {
  label: string;
  budget: number;
  items: AllocationItem[];
};

export type AllocationPlan = {
  capital: number;
  total_allocated: number;
  reserve: number;
  plan: Record<string, AllocationCategory>;
  projected_monthly_yield: number;
  projected_monthly_pct: number;
  existing_portfolio: { ticker: string; quantity: number; current_value: number }[];
  sector_allocation: Record<string, number>;
};

export type MacroData = {
  brent: number | null;
  usd_rate: number | null;
  imoex: number | null;
  key_rate: number | null;
  cpi: number | null;
  ofz_10y: number | null;
  m2: number | null;
};

export type PortfolioPosition = {
  id: number;
  ticker: string;
  quantity: number;
  avg_price: number | null;
  current_price: number | null;
  value: number;
  profit_pct: number | null;
};

export type TradePlan = {
  ticker: string;
  profile: string;
  current_price: number;
  entry_zone: { low: number; high: number; current: string };
  targets: Array<{ level: number; type: string; return_pct: number; rr: number }>;
  stop_loss: number;
  trailing_after: number;
  risk_reward: number;
};

export type AlertItem = {
  news_id: number;
  ticker: string;
  title: string;
  category: string;
  subcategory: string;
  source_name: string;
  published_at: string;
  priority: string;
  priority_score: number;
  anomaly_score: number;
  predicted_return: number;
  impact_confidence: number;
  in_portfolio: boolean;
  reason: string;
};
