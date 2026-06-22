"use client";

import { useState } from "react";
import { api } from "../lib/api";

type AuthState = { token: string | null; user: { id: number; username: string; email: string | null; role: string; risk_profile: string; is_active: boolean } | null };

function saveAuth(auth: AuthState) {
  localStorage.setItem("finn_auth", JSON.stringify(auth));
}

export default function AuthModal({ onClose, onAuth }: { onClose: () => void; onAuth: (s: AuthState) => void }) {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [riskProfile, setRiskProfile] = useState("balanced");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setError(""); setLoading(true);
    try {
      if (tab === "register") {
        const data = await api.auth.register(username, password, riskProfile);
        const user = await api.auth.me(data.access_token);
        const state: AuthState = { token: data.access_token, user };
        saveAuth(state);
        onAuth(state);
      } else {
        const data = await api.auth.login(username, password);
        const user = await api.auth.me(data.access_token);
        const state: AuthState = { token: data.access_token, user };
        saveAuth(state);
        onAuth(state);
      }
    } catch (e: any) {
      setError(e.message || "Ошибка");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[#0B1A2F] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4 backdrop-blur-sm" onClick={(e) => e.stopPropagation()}>
        <div className="flex gap-0 mb-5 bg-white/5 rounded-xl p-0.5">
          <button onClick={() => setTab("login")} className={`flex-1 py-2 text-xs font-medium rounded-lg transition ${tab === "login" ? "bg-amber-400/20 text-amber-400" : "text-gray-500"}`}>Вход</button>
          <button onClick={() => setTab("register")} className={`flex-1 py-2 text-xs font-medium rounded-lg transition ${tab === "register" ? "bg-amber-400/20 text-amber-400" : "text-gray-500"}`}>Регистрация</button>
        </div>
        <div className="space-y-3">
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Логин" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/50" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Пароль" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:border-amber-400/50" />
          {tab === "register" && (
            <select value={riskProfile} onChange={(e) => setRiskProfile(e.target.value)} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono text-white focus:outline-none focus:border-amber-400/50">
              <option value="conservative">Консервативный</option>
              <option value="balanced">Умеренный</option>
              <option value="aggressive">Агрессивный</option>
            </select>
          )}
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button onClick={handleSubmit} disabled={loading || !username || !password}
            className="w-full py-3 rounded-xl font-medium text-sm transition disabled:opacity-40"
            style={{ background: "linear-gradient(135deg, #F0B90B, #D4A107)", color: "#0B1A2F" }}>
            {loading ? "..." : tab === "login" ? "Войти" : "Зарегистрироваться"}
          </button>
        </div>
      </div>
    </div>
  );
}
