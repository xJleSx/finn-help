const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type ApiOptions = {
  token?: string | null;
  signal?: AbortSignal;
};

type RequestOptions = ApiOptions & {
  method?: string;
  body?: unknown;
};

type StoredAuth = {
  token: string;
  refreshToken: string;
  user: { id: number; username: string; email: string | null; role: string; risk_profile: string; is_active: boolean };
};

function getStoredAuth(): StoredAuth | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("finn_auth");
    if (!raw) return null;
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
}

function setStoredAuth(auth: StoredAuth): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("finn_auth", JSON.stringify(auth));
  } catch { /* ignore */ }
}

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  if (isRefreshing && refreshPromise) return refreshPromise;
  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const stored = getStoredAuth();
      if (!stored?.refreshToken) return false;
      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: stored.refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      setStoredAuth({ ...stored, token: data.access_token });
      return true;
    } catch {
      return false;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

function buildHeaders(token?: string | null, extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = opts;

  const getEffectiveToken = async (): Promise<string | null> => {
    if (token) return token;
    const stored = getStoredAuth();
    return stored?.token ?? null;
  };

  const doFetch = async (tok: string | null): Promise<Response> => {
    const headers = buildHeaders(tok, body ? { "Content-Type": "application/json" } : undefined);
    return fetch(`${API}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  };

  let resolvedToken = await getEffectiveToken();
  let res = await doFetch(resolvedToken);

  if (res.status === 401 && !token) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      resolvedToken = getStoredAuth()?.token ?? null;
      res = await doFetch(resolvedToken);
    }
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, text);
  }

  if (res.headers.get("content-type")?.includes("application/json")) {
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

export const api = {
  auth: {
    register: (username: string, password: string, riskProfile = "balanced") =>
      request<{ access_token: string; refresh_token: string; token_type: string; user_id: number; username: string }>(
        "/api/auth/register",
        { method: "POST", body: { username, password, risk_profile: riskProfile } },
      ),
    login: (username: string, password: string) =>
      request<{ access_token: string; refresh_token: string; token_type: string; user_id: number; username: string }>(
        "/api/auth/login",
        { method: "POST", body: { username, password } },
      ),
    me: (token: string) =>
      request<{ id: number; username: string; email: string | null; role: string; risk_profile: string; is_active: boolean }>(
        "/api/auth/me",
        { token },
      ),
    refresh: (refreshToken: string) =>
      request<{ access_token: string; token_type: string }>("/api/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshToken },
      }),
    logout: (refreshToken: string) =>
      request<{ status: string }>("/api/auth/logout", {
        method: "POST",
        body: { refresh_token: refreshToken },
      }),
  },

  instruments: {
    list: (type = "stock") =>
      request<Array<{ id: number; ticker: string; full_name: string; sector: string | null; type: string; last_price: number | null; last_date: string | null }>>(
        `/api/instruments?type=${type}`,
      ),
    detail: (ticker: string, opts?: ApiOptions) =>
      request<{ id: number; ticker: string; full_name: string; isin: string | null; sector: string | null; type: string; lot_size: number | null; currency: string | null }>(
        `/api/instruments/${ticker}`,
        opts,
      ),
    prices: (ticker: string, days = 365, opts?: ApiOptions) =>
      request<Array<{ date: string; open: number; high: number; low: number; close: number; volume: number | null }>>(
        `/api/instruments/${ticker}/prices?days=${days}`,
        opts,
      ),
    indicators: (ticker: string, days = 90, opts?: ApiOptions) =>
      request<Array<{ date: string; rsi: number | null; macd_line: number | null; macd_signal: number | null; macd_hist: number | null; sma_20: number | null; sma_50: number | null; sma_200: number | null; bb_upper: number | null; bb_lower: number | null; bb_mid: number | null; volume_sma_20: number | null; atr: number | null }>>(
        `/api/instruments/${ticker}/indicators?days=${days}`,
        opts,
      ),
    signal: (ticker: string, opts?: ApiOptions) =>
      request<Record<string, unknown>>(`/api/instruments/${ticker}/signal`, opts),
    tradePlan: (ticker: string, profile = "balanced", opts?: ApiOptions) =>
      request<{ ticker: string; profile: string; current_price: number; entry_zone: { low: number; high: number; current: string }; targets: Array<{ level: number; type: string; return_pct: number; rr: number }>; stop_loss: number; trailing_after: number; risk_reward: number }>(
        `/api/instruments/${ticker}/trade-plan?profile=${profile}`,
        opts,
      ),
    advice: (ticker: string, opts?: ApiOptions) =>
      request<{ signal: Record<string, unknown>; advice: string; user_id: number | null }>(
        `/api/instruments/${ticker}/advice`,
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
        plan: Record<string, {
          label: string;
          budget: number;
          items: Array<{ ticker: string; name: string; amount: number; reason: string; expected_yield: number }>;
        }>;
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
        `/api/alerts/divergence/${ticker}`,
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
        request<{ status: string }>(`/api/alert-preferences/mute/${ticker}`, { method: "POST", ...opts }),
      unmute: (ticker: string, opts?: ApiOptions) =>
        request<{ status: string }>(`/api/alert-preferences/unmute/${ticker}`, { method: "POST", ...opts }),
    },
  },

  analysis: {
    scenario: (opts?: ApiOptions) =>
      request<Record<string, unknown>>("/api/analysis/scenario", opts),
    riskPortfolio: (opts?: ApiOptions) =>
      request<Record<string, unknown>>("/api/risk/portfolio", opts),
    riskDeepDive: (ticker: string, opts?: ApiOptions) =>
      request<Record<string, unknown>>(`/api/risk/deep-dive/${ticker}`, opts),
    causal: (ticker: string, target?: string, opts?: ApiOptions) =>
      request<Record<string, unknown>>(
        `/api/analysis/causal/${ticker}${target ? `?target=${target}` : ""}`,
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
