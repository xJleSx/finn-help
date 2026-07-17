import {
  Building2,
  Hash,
  Ticket,
  Banknote,
  Percent,
  Calendar,
  CalendarCheck,
  Ban,
  RotateCcw,
} from "lucide-react";
import type { BondDetails } from "@/features/bonds/types/bond-details";
import OverviewGrid from "./OverviewGrid";
import OverviewItem from "./OverviewItem";

interface Props {
  details: BondDetails;
}

export default function BondOverviewCard({ details }: Props) {
  return (
    <div className="rounded-xl border bg-card p-6">
      <h3 className="mb-6 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Основная информация
      </h3>
      <OverviewGrid>
        <OverviewItem
          label="Эмитент"
          value={details.issuer}
          icon={<Building2 className="h-3.5 w-3.5" />}
        />
        <OverviewItem label="ISIN" value={details.isin} icon={<Hash className="h-3.5 w-3.5" />} />
        <OverviewItem
          label="Тикер"
          value={details.ticker}
          icon={<Ticket className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Номинал"
          value={`${details.nominal.toLocaleString("ru-RU")} ₽`}
          icon={<Banknote className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Валюта"
          value={details.currency}
          icon={<Banknote className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Купон"
          value={`${details.couponRate.toFixed(1)}%`}
          icon={<Percent className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Выпуск"
          value={new Date(details.issueDate).toLocaleDateString("ru-RU", {
            year: "numeric",
            month: "short",
          })}
          icon={<Calendar className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Погашение"
          value={new Date(details.maturityDate).toLocaleDateString("ru-RU", {
            year: "numeric",
            month: "short",
          })}
          icon={<CalendarCheck className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Оферта"
          value={details.offerDate ?? "Нет"}
          icon={<Ban className="h-3.5 w-3.5" />}
        />
        <OverviewItem
          label="Амортизация"
          value={details.amortization ? "Да" : "Нет"}
          icon={<RotateCcw className="h-3.5 w-3.5" />}
        />
      </OverviewGrid>
    </div>
  );
}
