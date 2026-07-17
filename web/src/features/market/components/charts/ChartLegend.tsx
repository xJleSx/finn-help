"use client";

import { Eye, EyeOff } from "lucide-react";
import type { ReactNode } from "react";

export interface ChartLegendItem {
  id: string;
  label: string;
  color: string;
  active: boolean;
  onToggle: () => void;
}

interface Props {
  items: ChartLegendItem[];
  extra?: ReactNode;
}

export default function ChartLegend({ items, extra }: Props) {
  if (items.length === 0 && !extra) return null;

  return (
    <div className="flex flex-wrap items-center gap-3">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={item.onToggle}
          className="flex items-center gap-1.5 text-xs"
        >
          {item.active ? (
            <Eye className="h-3 w-3 text-muted-foreground" />
          ) : (
            <EyeOff className="h-3 w-3 text-muted-foreground/50" />
          )}
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            <span className={item.active ? "text-foreground" : "text-muted-foreground/50"}>
              {item.label}
            </span>
          </span>
        </button>
      ))}
      {extra}
    </div>
  );
}
