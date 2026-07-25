"use client";

import { createContext, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getUserFromCookie, setUserCookie, type UserInfo } from "@/lib/auth";

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

const REFRESH_INTERVAL_MS = 15 * 60 * 1000;

async function fetchMe(): Promise<UserInfo | null> {
  try {
    const res = await fetch("/api/auth/me");
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const queryClient = useQueryClient();
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const init = async () => {
      const cached = getUserFromCookie();
      if (cached) {
        setUser(cached);
        setIsLoading(false);
        return;
      }
      const me = await fetchMe();
      if (me) {
        setUser(me);
        setUserCookie(me);
      }
      setIsLoading(false);
    };
    init();
  }, []);

  const doRefresh = useCallback(async () => {
    try {
      const res = await fetch("/api/auth/refresh", { method: "POST" });
      if (res.ok) {
        const me = await fetchMe();
        if (me) {
          setUser(me);
          setUserCookie(me);
        }
        return true;
      }
      setUser(null);
      setUserCookie(null);
      return false;
    } catch (e) {
      console.error("Token refresh failed", e);
      return false;
    }
  }, []);

  useEffect(() => {
    if (!user) return;

    const refresh = async () => {
      await doRefresh();
      refreshTimerRef.current = setTimeout(refresh, REFRESH_INTERVAL_MS);
    };

    refreshTimerRef.current = setTimeout(refresh, REFRESH_INTERVAL_MS);

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [user, doRefresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Login failed" }));
      throw new Error(err.error);
    }

    const me = await fetchMe();
    if (me) {
      setUser(me);
      setUserCookie(me);
    }
  }, []);

  const register = useCallback(async (username: string, password: string, riskProfile = "balanced") => {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, risk_profile: riskProfile }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Registration failed" }));
      throw new Error(err.error);
    }

    const me = await fetchMe();
    if (me) {
      setUser(me);
      setUserCookie(me);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch (e) {
      console.error("Logout API call failed", e);
    }
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    setUserCookie(null);
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  return (
    <AuthContext.Provider value={{ token: user ? "authenticated" : null, refreshToken: null, user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
