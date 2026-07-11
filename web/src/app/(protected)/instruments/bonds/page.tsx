"use client";

import BondDashboard from "@/components/market/bonds/BondDashboard";
import { useBonds } from "@/hooks/bonds/useBond";

export default function BondsPage() {
  const { data: bonds, isLoading, error } = useBonds();

  if (isLoading) {
    return (
      <div className="p-8 text-white">
        Загрузка облигаций...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-red-400">
        Не удалось загрузить облигации
      </div>
    );
  }

  return (
    <main className="space-y-8 p-8">
      <div>
        <h1 className="text-4xl font-bold text-white">
          Облигации
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Управление портфелем облигаций
        </p>
      </div>
      <BondDashboard bonds={bonds ?? []} />
    </main>
  );
}
