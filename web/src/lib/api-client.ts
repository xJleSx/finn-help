import { type UserInfo } from "./auth";

type ApiOptions = {
  token?: string | null;
  signal?: AbortSignal;
};

type RequestOptions = ApiOptions & {
  method?: string;
  body?: unknown;
};

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = opts;

  const headers: Record<string, string> = {};
  if (body) {
    headers["Content-Type"] = "application/json";
  }

  let res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });

  if (res.status === 401) {
    const refreshRes = await fetch("/api/auth/refresh", { method: "POST" });
    if (refreshRes.ok) {
      res = await fetch(path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
        signal,
      });
    }
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, text);
  }

  const contentType = res.headers.get("content-type");
  if (contentType?.includes("application/json")) {
    return res.json();
  }

  return res.text() as unknown as T;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type LoginResponse = { user_id: number; username: string };
type MeResponse = UserInfo;

async function authFetch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Request failed");
    throw new ApiError(res.status, text);
  }
  return res.json();
}

export const api = {
  auth: {
    register: (username: string, password: string, riskProfile = "balanced") =>
      authFetch<LoginResponse>("/api/auth/register", { username, password, risk_profile: riskProfile }),
    login: (username: string, password: string) =>
      authFetch<LoginResponse>("/api/auth/login", { username, password }),
    me: () =>
      request<MeResponse>("/api/auth/me"),
    refresh: () =>
      request<{ status: string }>("/api/auth/refresh", { method: "POST" }),
    logout: () =>
      request<{ status: string }>("/api/auth/logout", { method: "POST" }),
  },

  instruments: {
    list: (type = "stock") =>
      request<Array<{ id: number; ticker: string; full_name: string; sector: string | null; type: string; last_price: number | null; last_date: string | null }>>(
        `/api/instruments?type=${encodeURIComponent(type)}`,
      ),
    detail: (ticker: string, opts?: ApiOptions) =>
      request<{ id: number; ticker: string; full_name: string; isin: string | null; sector: string | null; type: string; lot_size: number | null; currency: string | null }>(
        `/api/instruments/${encodeURIComponent(ticker)}`,
        opts,
      ),
    prices: (ticker: string, days = 365, opts?: ApiOptions) =>
      request<Array<{ date: string; open: number; high: number; low: number; close: number; volume: number | null }>>(
        `/api/instruments/${encodeURIComponent(ticker)}/prices?days=${days}`,
        opts,
      ),
    indicators: (ticker: string, days = 90, opts?: ApiOptions) =>
      request<Array<{ date: string; rsi: number | null; macd_line: number | null; macd_signal: number | null; macd_hist: number | null; sma_20: number | null; sma_50: number | null; sma_200: number | null; bb_upper: number | null; bb_lower: number | null; bb_mid: number | null; volume_sma_20: number | null; atr: number | null }>>(
        `/api/instruments/${encodeURIComponent(ticker)}/indicators?days=${days}`,
        opts,
      ),
    signal: (ticker: string, opts?: ApiOptions) =>
      request<Record<string, unknown>>(`/api/instruments/${encodeURIComponent(ticker)}/signal`, opts),
    tradePlan: (ticker: string, profile = "balanced", opts?: ApiOptions) =>
      request<{ ticker: string; profile: string; current_price: number; entry_zone: { low: number; high: number; current: string }; targets: Array<{ level: number; type: string; return_pct: number; rr: number }>; stop_loss: number; trailing_after: number; risk_reward: number }>(
        `/api/instruments/${encodeURIComponent(ticker)}/trade-plan?profile=${encodeURIComponent(profile)}`,
        opts,
      ),
    advice: (ticker: string, opts?: ApiOptions) =>
      request<{ signal: Record<string, unknown>; advice: string; user_id: number | null }>(
        `/api/instruments/${encodeURIComponent(ticker)}/advice`,
        opts,
      ),
  },

  news: {
    list: (limit = 20, opts?: ApiOptions) =>
      request<Array<{ id: number; title: string; summary: string | null; source: string; url: string; published_at: string | null }>>(
        `/api/news?limit=${limit}`,
        opts,
      ),
  },

  geo: {
    history: (days = 30, opts?: ApiOptions) =>
      request<Array<{ date: string; score: number; components: Record<string, unknown> | null }>>(
        `/api/geo-risk?days=${days}`,
        opts,
      ),
  },

  macro: {
    latest: (opts?: ApiOptions) =>
      request<Record<string, unknown>>("/api/macro", opts),
  },

  sectors: {
    performance: (days = 30, opts?: ApiOptions) =>
      request<Record<string, number>>(`/api/sectors/performance?days=${days}`, opts),
  },

  portfolio: {
    list: (opts?: ApiOptions) =>
      request<Array<{ id: number; ticker: string; quantity: number; avg_price: number | null; current_price: number | null; value: number; profit_pct: number | null }>>(
        "/api/portfolio",
        opts,
      ),
    add: (ticker: string, quantity: number, avgPrice?: number | null, opts?: ApiOptions) =>
      request<{ status: string }>("/api/portfolio/add", {
        method: "POST",
        body: { ticker, quantity, avg_price: avgPrice ?? null },
        ...opts,
      }),
    allocate: (capital: number, opts?: ApiOptions) =>
      request<{
        capital: number;
        total_allocated: number;
        reserve: number;
        plan: Record<string, { label: string; budget: number; items: Array<{ ticker: string; name: string; amount: number; reason: string; expected_yield: number }> }>;
        projected_monthly_yield: number;
        projected_monthly_pct: number;
        existing_portfolio: Array<{ ticker: string; quantity: number; current_value: number }>;
        sector_allocation: Record<string, number>;
      }>(`/api/portfolio/allocate?capital=${capital}`, {
        method: "POST",
        ...opts,
      }),
  },

  alerts: {
    list: (limit = 20, opts?: ApiOptions) =>
      request<{ alerts: Array<Record<string, unknown>> }>(`/api/alerts?limit=${limit}`, opts),
    refresh: (opts?: ApiOptions) =>
      request<{ new_alerts: number }>("/api/alerts/refresh", { method: "POST", ...opts }),
    analytics: (days = 30, opts?: ApiOptions) =>
      request<Record<string, unknown>>(`/api/alerts/analytics?days=${days}`, opts),
    priceTargets: (opts?: ApiOptions) =>
      request<Array<{ ticker: string; current_price: number; target_price: number; target_type: string; triggered_pct: number }>>(
        "/api/alerts/price-targets",
        opts,
      ),
    divergence: (ticker: string, opts?: ApiOptions) =>
      request<Array<{ ticker: string; divergence_type: string; indicator: string; strength: number }>>(
        `/api/alerts/divergence/${encodeURIComponent(ticker)}`,
        opts,
      ),
    rebalance: (opts?: ApiOptions) =>
      request<Array<{ ticker: string; current_pct: number; target_pct: number; deviation_pct: number; reason: string }>>(
        "/api/alerts/rebalance",
        opts,
      ),
    preferences: {
      get: (opts?: ApiOptions) =>
        request<{ min_severity: string; muted_tickers: string[]; quiet_hours_start: string | null; quiet_hours_end: string | null }>(
          "/api/alert-preferences",
          opts,
        ),
      update: (body: { min_severity?: string; quiet_hours_start?: string | null; quiet_hours_end?: string | null }, opts?: ApiOptions) =>
        request<{ min_severity: string; muted_tickers: string[]; quiet_hours_start: string | null; quiet_hours_end: string | null }>(
          "/api/alert-preferences",
          { method: "PUT", body, ...opts },
        ),
      mute: (ticker: string, opts?: ApiOptions) =>
        request<{ status: string }>(`/api/alert-preferences/mute/${encodeURIComponent(ticker)}`, { method: "POST", ...opts }),
      unmute: (ticker: string, opts?: ApiOptions) =>
        request<{ status: string }>(`/api/alert-preferences/unmute/${encodeURIComponent(ticker)}`, { method: "POST", ...opts }),
    },
  },

  analysis: {
    scenario: (opts?: ApiOptions) =>
      request<Record<string, unknown>>("/api/analysis/scenario", opts),
    riskPortfolio: (opts?: ApiOptions) =>
      request<Record<string, unknown>>("/api/risk/portfolio", opts),
    riskDeepDive: (ticker: string, opts?: ApiOptions) =>
      request<Record<string, unknown>>(`/api/risk/deep-dive/${encodeURIComponent(ticker)}`, opts),
    causal: (ticker: string, target?: string, opts?: ApiOptions) =>
      request<Record<string, unknown>>(
        `/api/analysis/causal/${encodeURIComponent(ticker)}${target ? `?target=${encodeURIComponent(target)}` : ""}`,
        opts,
      ),
  },

  paper: {
    status: (opts?: ApiOptions) =>
      request<{
        balance: number;
        initial_capital: number;
        total_equity: number;
        total_return_pct: number;
        positions: Array<{ ticker: string; quantity: number; avg_price: number; value: number }>;
        n_trades: number;
        start_time: string;
      }>("/api/paper/status", opts),
    order: (body: { ticker: string; direction: string; quantity: number; price?: number; reason?: string }, opts?: ApiOptions) =>
      request<{ status: string; ticker: string; direction: string; quantity: number; price: number; pnl: number; balance_after: number; total_equity: number }>(
        "/api/paper/order",
        { method: "POST", body, ...opts },
      ),
    orders: (limit = 20, opts?: ApiOptions) =>
      request<{ trades: Array<Record<string, unknown>>; total: number }>(`/api/paper/orders?limit=${limit}`, opts),
    reset: (capital = 1_000_000, opts?: ApiOptions) =>
      request<{ status: string; balance: number; initial_capital: number }>(
        `/api/paper/reset?initial_capital=${capital}`,
        { method: "POST", ...opts },
      ),
    metrics: (opts?: ApiOptions) =>
      request<Record<string, unknown>>("/api/paper/metrics", opts),
    equityCurve: (opts?: ApiOptions) =>
      request<{ equity_curve: number[] }>("/api/paper/equity-curve", opts),
  },
};
