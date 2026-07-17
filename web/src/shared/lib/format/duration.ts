export function formatDuration(years: number): string {
  if (years < 1) {
    const months = Math.round(years * 12);
    return `${months} мес`;
  }
  return `${years.toFixed(1)} лет`;
}
