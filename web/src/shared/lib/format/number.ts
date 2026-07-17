export function formatNumber(v: number, decimals = 2): string {
  return v.toLocaleString("ru-RU", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function formatNumberCompact(v: number, decimals = 1): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(decimals)} млн`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(decimals)} тыс`;
  return formatNumber(v, decimals);
}
