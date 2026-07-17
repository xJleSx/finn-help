type RequestOptions = RequestInit & {
  params?: Record<string, string>;
};

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl = "/api/proxy") {
    this.baseUrl = baseUrl;
  }

  private buildUrl(path: string, params?: Record<string, string>): string {
    const url = new URL(`${this.baseUrl}${path}`, window.location.origin);
    if (params) {
      Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    }
    return url.toString();
  }

  async get<T>(path: string, opts?: RequestOptions): Promise<T> {
    const res = await fetch(this.buildUrl(path, opts?.params), {
      method: "GET",
      headers: { "Content-Type": "application/json", ...opts?.headers },
      ...opts,
    });
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
    return res.json();
  }

  async post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    const res = await fetch(this.buildUrl(path, opts?.params), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...opts?.headers },
      body: body ? JSON.stringify(body) : undefined,
      ...opts,
    });
    if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
    return res.json();
  }

  async delete<T>(path: string, opts?: RequestOptions): Promise<T> {
    const res = await fetch(this.buildUrl(path, opts?.params), {
      method: "DELETE",
      headers: { "Content-Type": "application/json", ...opts?.headers },
      ...opts,
    });
    if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`);
    return res.json();
  }
}

export const api = new ApiClient();
