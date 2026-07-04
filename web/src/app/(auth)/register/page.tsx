import type { Metadata } from "next";
import { RegisterForm } from "@/components/RegisterForm";

export const metadata: Metadata = {
  title: "Регистрация — FinAdvisor",
};

export default function RegisterPage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-medium text-white">Регистрация</h2>
        <p className="text-sm text-gray-500 mt-1">Создайте аккаунт для управления портфелем</p>
      </div>
      <RegisterForm />
      <p className="text-center text-sm text-gray-500">
        Уже есть аккаунт?{" "}
        <a href="/login" className="text-amber-400 hover:text-amber-300 transition">
          Войти
        </a>
      </p>
    </div>
  );
}
