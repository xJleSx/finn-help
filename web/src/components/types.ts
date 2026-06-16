export type Instrument = {
  id: number; ticker: string; full_name: string; type: string;
  last_price: number | null; last_date: string | null;
};

export type News = {
  id: number; title: string; summary: string; source: string; url: string; published_at: string | null;
};

export type GeoRisk = {
  date: string; score: number;
};

export type DashboardData = {
  instruments: number; signals: number; last_update: string | null; timestamp: string;
};

export type AllocationItem = {
  ticker: string; name: string; amount: number; reason: string; expected_yield: number;
};

export type AllocationCategory = {
  label: string; budget: number; items: AllocationItem[];
};

export type AllocationPlan = {
  capital: number; total_allocated: number; reserve: number;
  plan: Record<string, AllocationCategory>;
  projected_monthly_yield: number; projected_monthly_pct: number;
  existing_portfolio: { ticker: string; quantity: number; current_value: number }[];
  sector_allocation: Record<string, number>;
};

export type UserInfo = {
  id: number; username: string; email: string | null; role: string; risk_profile: string; is_active: boolean;
};

export type AuthState = {
  token: string | null; user: UserInfo | null;
};
