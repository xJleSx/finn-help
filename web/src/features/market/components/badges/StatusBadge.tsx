export type Status = "paid" | "pending" | "forecast" | "active" | "inactive" | "error";

interface Props {
  status: Status;
}

const CONFIG: Record<Status, { label: string; className: string }> = {
  paid: { label: "Выплачен", className: "bg-emerald-500/15 text-emerald-500" },
  pending: { label: "Ожидается", className: "bg-yellow-500/15 text-yellow-500" },
  forecast: { label: "Прогноз", className: "bg-muted text-muted-foreground" },
  active: { label: "Активен", className: "bg-emerald-500/15 text-emerald-500" },
  inactive: { label: "Неактивен", className: "bg-muted text-muted-foreground" },
  error: { label: "Ошибка", className: "bg-red-500/15 text-red-500" },
};

export default function StatusBadge({ status }: Props) {
  const cfg = CONFIG[status] ?? CONFIG.error;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}
