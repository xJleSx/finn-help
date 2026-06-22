const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

function authHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

async function get<T>(path: string, token?: string | null): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: { ...authHeaders(token ?? null) } });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function post<T>(path: string, body?: unknown, token?: string | null): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token ?? null) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const api = {
  instruments: {
    list: (type = "stock") => get<any[]>(`/api/instruments?type=${type}`),
    prices: (ticker: string, days: number) => get<any[]>(`/api/instruments/${ticker}/prices?days=${days}`),
    advice: (ticker: string) => get<any>(`/api/instruments/${ticker}/advice`),
  },
  news: {
    list: (limit = 5) => get<any[]>(`/api/news?limit=${limit}`),
  },
  geo: {
    history: (days = 14) => get<any[]>(`/api/geo-risk?days=${days}`),
  },
  macro: {
    latest: () => get<any>("/api/macro"),
  },
  sectors: {
    performance: (days = 30) => get<Record<string, number>>(`/api/sectors/performance?days=${days}`),
  },
  portfolio: {
    allocate: (capital: number) => post<any>(`/api/portfolio/allocate?capital=${capital}`),
  },
  auth: {
    register: (username: string, password: string, riskProfile = "balanced") =>
      post<any>("/api/auth/register", { username, password, risk_profile: riskProfile }),
    login: (username: string, password: string) =>
      post<any>("/api/auth/login", { username, password }),
    me: (token: string) => get<any>("/api/auth/me", token),
  },
};
