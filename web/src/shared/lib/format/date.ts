export function formatDate(date: string | Date, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("ru-RU", options ?? {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatDateShort(date: string | Date): string {
  return formatDate(date, { day: "numeric", month: "short" });
}

export function formatDateTime(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays > 0) return `через ${diffDays} дн`;
  if (diffDays === 0) return "сегодня";
  if (diffDays === -1) return "вчера";
  return `просрочено ${Math.abs(diffDays)} дн`;
}
