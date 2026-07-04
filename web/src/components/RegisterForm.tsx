"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { z } from "zod";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api-client";

const registerSchema = z.object({
  username: z.string().min(3, "Минимум 3 символа").max(50).regex(/^[a-zA-Z0-9_]+$/, "Только буквы, цифры и _"),
  password: z.string().min(8, "Минимум 8 символов"),
  confirmPassword: z.string(),
  riskProfile: z.enum(["conservative", "balanced", "aggressive"]),
}).refine((d) => d.password === d.confirmPassword, {
  message: "Пароли не совпадают",
  path: ["confirmPassword"],
});

const riskProfiles = [
  { value: "conservative", label: "Консервативный", desc: "Низкий риск, стабильный доход" },
  { value: "balanced", label: "Умеренный", desc: "Баланс риска и доходности" },
  { value: "aggressive", label: "Агрессивный", desc: "Высокий риск, высокий потенциал" },
];

export function RegisterForm() {
  const router = useRouter();
  const { register } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [riskProfile, setRiskProfile] = useState("balanced");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErrors({});

    const result = registerSchema.safeParse({ username, password, confirmPassword, riskProfile });
    if (!result.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        if (issue.path[0]) fieldErrors[String(issue.path[0])] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }

    setLoading(true);
    try {
      await register(username, password, riskProfile);
      toast.success("Регистрация успешна");
      router.push("/dashboard");
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Ошибка регистрации";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="reg-username" className="block text-sm text-gray-400 mb-1">Имя пользователя</label>
        <input
          id="reg-username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-amber-400/50 transition"
          placeholder="username"
          autoComplete="username"
        />
        {errors.username && <p className="text-red-400 text-xs mt-1">{errors.username}</p>}
      </div>
      <div>
        <label htmlFor="reg-password" className="block text-sm text-gray-400 mb-1">Пароль</label>
        <input
          id="reg-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-amber-400/50 transition"
          placeholder="••••••••"
          autoComplete="new-password"
        />
        {errors.password && <p className="text-red-400 text-xs mt-1">{errors.password}</p>}
      </div>
      <div>
        <label htmlFor="reg-confirm" className="block text-sm text-gray-400 mb-1">Подтверждение пароля</label>
        <input
          id="reg-confirm"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-amber-400/50 transition"
          placeholder="••••••••"
          autoComplete="new-password"
        />
        {errors.confirmPassword && <p className="text-red-400 text-xs mt-1">{errors.confirmPassword}</p>}
      </div>
      <div>
        <label className="block text-sm text-gray-400 mb-2">Профиль риска</label>
        <div className="space-y-2">
          {riskProfiles.map((rp) => (
            <label
              key={rp.value}
              className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition ${
                riskProfile === rp.value
                  ? "border-amber-400/50 bg-amber-400/5"
                  : "border-white/10 bg-white/5 hover:border-white/20"
              }`}
            >
              <input
                type="radio"
                name="riskProfile"
                value={rp.value}
                checked={riskProfile === rp.value}
                onChange={(e) => setRiskProfile(e.target.value)}
                className="accent-amber-400"
              />
              <div>
                <p className="text-sm font-medium text-white">{rp.label}</p>
                <p className="text-xs text-gray-500">{rp.desc}</p>
              </div>
            </label>
          ))}
        </div>
        {errors.riskProfile && <p className="text-red-400 text-xs mt-1">{errors.riskProfile}</p>}
      </div>
      <button
        type="submit"
        disabled={loading}
        className="w-full py-2 rounded-lg font-medium transition bg-amber-500 hover:bg-amber-400 text-gray-900 disabled:opacity-50"
      >
        {loading ? "..." : "Зарегистрироваться"}
      </button>
    </form>
  );
}
