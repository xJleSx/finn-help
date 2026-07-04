import type { Metadata } from "next";
import { LoginForm } from "@/components/LoginForm";

export const metadata: Metadata = {
  title: "Вход — FinAdvisor",
};

export default function LoginPage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-medium text-white">Вход</h2>
        <p className="text-sm text-gray-500 mt-1">Войдите в аккаунт для доступа к портфелю и алертам</p>
      </div>
      <LoginForm />
      <p className="text-center text-sm text-gray-500">
        Нет аккаунта?{" "}
        <a href="/register" className="text-amber-400 hover:text-amber-300 transition">
          Зарегистрироваться
        </a>
      </p>
    </div>
  );
}
