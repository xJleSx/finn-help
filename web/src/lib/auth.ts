import { jwtVerify, type JWTPayload } from "jose";

const AUTH_KEY = "finn_auth";

export type StoredAuth = {
  token: string;
  refreshToken: string;
  user: UserInfo;
};

export type UserInfo = {
  id: number;
  username: string;
  email: string | null;
  role: string;
  risk_profile: string;
  is_active: boolean;
};

export type AuthState =
  | { status: "authenticated"; token: string; refreshToken: string; user: UserInfo }
  | { status: "unauthenticated" }
  | { status: "loading" };

function getSecret(): Uint8Array {
  const secret = process.env.JWT_SECRET || "fallback-secret-do-not-use-in-production";
  return new TextEncoder().encode(secret);
}

export async function decodeToken(token: string): Promise<JWTPayload | null> {
  try {
    const { payload } = await jwtVerify(token, getSecret());
    return payload;
  } catch {
    return null;
  }
}

export function isTokenExpired(payload: JWTPayload): boolean {
  if (!payload.exp) return true;
  return Date.now() >= payload.exp * 1000;
}

export function getTokenExpiry(payload: JWTPayload): number {
  return payload.exp ? payload.exp * 1000 : 0;
}

export function storeAuth(auth: StoredAuth): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
  } catch { /* ignore */ }
}

export function loadAuth(): AuthState {
  if (typeof window === "undefined") return { status: "loading" };
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (!raw) return { status: "unauthenticated" };
    const parsed: StoredAuth = JSON.parse(raw);
    if (!parsed.token || !parsed.refreshToken || !parsed.user) {
      clearAuth();
      return { status: "unauthenticated" };
    }
    return {
      status: "authenticated",
      token: parsed.token,
      refreshToken: parsed.refreshToken,
      user: parsed.user,
    };
  } catch {
    return { status: "unauthenticated" };
  }
}

export async function refreshAuthToken(refreshToken: string): Promise<{ token: string } | null> {
  const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${API}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return { token: data.access_token };
  } catch {
    return null;
  }
}

export function clearAuth(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch { /* ignore */ }
}
