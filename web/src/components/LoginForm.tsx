"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { z } from "zod";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api-client";

const loginSchema = z.object({
  username: z.string().min(3, "Минимум 3 символа"),
  password: z.string().min(1, "Введите пароль"),
});

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErrors({});

    const result = loginSchema.safeParse({ username, password });
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
      await login(username, password);
      toast.success("Вход выполнен");
      router.push("/dashboard");
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Ошибка входа";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="login-username" className="block text-sm text-gray-400 mb-1">Имя пользователя</label>
        <input
          id="login-username"
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
        <label htmlFor="login-password" className="block text-sm text-gray-400 mb-1">Пароль</label>
        <input
          id="login-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-amber-400/50 transition"
          placeholder="••••••••"
          autoComplete="current-password"
        />
        {errors.password && <p className="text-red-400 text-xs mt-1">{errors.password}</p>}
      </div>
      <button
        type="submit"
        disabled={loading}
        className="w-full py-2 rounded-lg font-medium transition bg-amber-500 hover:bg-amber-400 text-gray-900 disabled:opacity-50"
      >
        {loading ? "..." : "Войти"}
      </button>
    </form>
  );
}
