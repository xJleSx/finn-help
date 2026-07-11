import { useState, useEffect } from "react";

interface Props {
  date: Date;
}

function getDaysUntil(date: Date): number {
  const now = new Date();
  const diff = date.getTime() - now.getTime();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

export default function DateWithCountdown({ date }: Props) {
  const [days, setDays] = useState(() => getDaysUntil(date));

  useEffect(() => {
    const timer = setInterval(() => setDays(getDaysUntil(date)), 60_000);
    return () => clearInterval(timer);
  }, [date]);

  const formatted = date.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
  });

  return (
    <div className="tabular-nums">
      <div className="text-sm text-muted-foreground">
        📅 {formatted}
      </div>
      <div className="text-xs text-muted-foreground/70">
        {days > 0 ? `через ${days} дн` : days === 0 ? "сегодня" : `просрочено ${Math.abs(days)} дн`}
      </div>
    </div>
  );
}
