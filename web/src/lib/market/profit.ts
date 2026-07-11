export function getProfitInfo(profit: number, invested: number): {
  label: string;
  percent: number;
  positive: boolean;
} {
  const percent = invested > 0 ? (profit / invested) * 100 : 0;
  return {
    label: profit >= 0 ? `+${profit.toLocaleString("ru-RU")} ₽` : `${profit.toLocaleString("ru-RU")} ₽`,
    percent,
    positive: profit >= 0,
  };
}

export function getProfitColor(positive: boolean): string {
  return positive ? "text-emerald-500" : "text-red-500";
}
