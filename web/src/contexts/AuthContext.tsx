"use client";

import { createContext, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import {
  storeAuth,
  loadAuth,
  clearAuth as clearStoredAuth,
  refreshAuthToken,
  decodeToken,
  getTokenExpiry,
  type UserInfo,
} from "@/lib/auth";

export type AuthContextValue = {
  token: string | null;
  refreshToken: string | null;
  user: UserInfo | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, riskProfile?: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

function setAuthCookie(token: string | null) {
  if (typeof document === "undefined") return;
  if (token) {
    const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toUTCString();
    document.cookie = `finn_auth_token=${token}; path=/; expires=${expires}; SameSite=Lax; Secure`;
  } else {
    document.cookie = "finn_auth_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; Secure";
  }
}

function initAuthState() {
  const state = loadAuth();
  if (state.status === "authenticated") {
    setAuthCookie(state.token);
    return { token: state.token, refreshToken: state.refreshToken, user: state.user, isLoading: false };
  }
  return { token: null, refreshToken: null, user: null, isLoading: false };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [{ token, refreshToken, user }, setState] = useState(() => {
    const s = initAuthState();
    return { token: s.token, refreshToken: s.refreshToken, user: s.user };
  });
  const [isLoading] = useState(false);
  const queryClient = useQueryClient();
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleRefreshRef = useRef<((tok: string, refTok: string) => Promise<void>) | null>(null);

  const scheduleRefresh = useCallback(async (tok: string, refTok: string) => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);

    try {
      const payload = await decodeToken(tok);
      if (!payload) return;

      const expiresAt = getTokenExpiry(payload);
      const now = Date.now();
      const msUntilRefresh = Math.max(0, expiresAt - now - 60_000);

      const doRefresh = async () => {
        const result = await refreshAuthToken(refTok);
        if (result) {
          const stored = loadAuth();
          if (stored.status === "authenticated") {
            storeAuth({ ...stored, token: result.token });
            setAuthCookie(result.token);
            setState((prev) => ({ ...prev, token: result.token }));
            scheduleRefreshRef.current?.(result.token, refTok);
          }
        }
      };

      if (msUntilRefresh <= 0) {
        await doRefresh();
      } else {
        refreshTimerRef.current = setTimeout(doRefresh, msUntilRefresh);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    scheduleRefreshRef.current = scheduleRefresh;
  }, [scheduleRefresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.auth.login(username, password);
    const me = await api.auth.me(res.access_token);
    const userInfo: UserInfo = {
      id: me.id,
      username: me.username,
      email: me.email,
      role: me.role,
      risk_profile: me.risk_profile,
      is_active: me.is_active,
    };
    storeAuth({ token: res.access_token, refreshToken: res.refresh_token, user: userInfo });
    setState({ token: res.access_token, refreshToken: res.refresh_token, user: userInfo });
    setAuthCookie(res.access_token);
    scheduleRefresh(res.access_token, res.refresh_token);
  }, [scheduleRefresh]);

  const register = useCallback(async (username: string, password: string, riskProfile = "balanced") => {
    const res = await api.auth.register(username, password, riskProfile);
    const me = await api.auth.me(res.access_token);
    const userInfo: UserInfo = {
      id: me.id,
      username: me.username,
      email: me.email,
      role: me.role,
      risk_profile: me.risk_profile,
      is_active: me.is_active,
    };
    storeAuth({ token: res.access_token, refreshToken: res.refresh_token, user: userInfo });
    setState({ token: res.access_token, refreshToken: res.refresh_token, user: userInfo });
    setAuthCookie(res.access_token);
    scheduleRefresh(res.access_token, res.refresh_token);
  }, [scheduleRefresh]);

  const logout = useCallback(async () => {
    if (refreshToken) {
      try {
        await api.auth.logout(refreshToken);
      } catch { /* ignore */ }
    }
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    clearStoredAuth();
    setAuthCookie(null);
    queryClient.clear();
    setState({ token: null, refreshToken: null, user: null });
  }, [refreshToken, queryClient]);

  useEffect(() => {
    if (token && refreshToken) {
      scheduleRefresh(token, refreshToken);
    }
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [token, refreshToken, scheduleRefresh]);

  return (
    <AuthContext.Provider value={{ token, refreshToken, user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
