export function formatPercent(v: number, digits = 2): string {
  return `${v.toFixed(digits)}%`;
}

export function formatPercentWithSign(v: number, digits = 2): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}
