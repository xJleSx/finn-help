export function formatCurrency(v: number, currency = "₽"): string {
  return `${v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export function formatCurrencyCompact(v: number, currency = "₽"): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)} млн ${currency}`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)} тыс ${currency}`;
  return formatCurrency(v, currency);
}
