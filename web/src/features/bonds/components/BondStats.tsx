"use client";

import StatCard from "@/features/market/components/cards/StatCard";
import { Bond } from "@/features/bonds/types/bond";

interface Props {
  bonds: Bond[];
}

export default function BondStats({ bonds }: Props) {
  const portfolioValue = bonds.reduce(
    (sum, bond) => sum + bond.currentValue,
    0,
  );
  const invested = bonds.reduce(
    (sum, bond) => sum + bond.invested,
    0,
  );
  const averageYtm =
    bonds.length === 0
      ? 0
      : bonds.reduce(
          (sum, bond) => sum + bond.yieldToMaturity,
          0,
        ) / bonds.length;
  const nextCoupon = bonds
    .map((b) => new Date(b.nextCouponDate))
    .sort((a, b) => a.getTime() - b.getTime())[0];
  const totalCoupons = bonds.reduce(
    (sum, bond) => sum + bond.couponValue * bond.quantity,
    0,
  );

  return (
    <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
      <StatCard
        title="Стоимость портфеля"
        value={`${portfolioValue.toLocaleString()} ₽`}
        subtitle={`Вложено ${invested.toLocaleString()} ₽`}
      />
      <StatCard
        title="Средний YTM"
        value={`${averageYtm.toFixed(2)} %`}
        subtitle="Доходность к погашению"
      />
      <StatCard
        title="Следующий купон"
        value={
          nextCoupon
            ? nextCoupon.toLocaleDateString("ru-RU")
            : "—"
        }
        subtitle="Ближайшая выплата"
      />
      <StatCard
        title="Купоны за период"
        value={`${totalCoupons.toLocaleString()} ₽`}
        subtitle="По текущему портфелю"
      />
    </section>
  );
}
