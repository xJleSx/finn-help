"use client";

import { Columns3 } from "lucide-react";
import { useState, useRef, useEffect } from "react";

interface ColumnOption {
  id: string;
  label: string;
  visible: boolean;
}

interface Props {
  columns: ColumnOption[];
  onChange: (columnId: string, visible: boolean) => void;
}

export default function ColumnSelector({ columns, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
      >
        <Columns3 className="h-3.5 w-3.5" />
        Колонки
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-48 rounded-lg border border-border bg-popover p-2 shadow-lg">
          {columns.map((col) => (
            <label
              key={col.id}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
            >
              <input
                type="checkbox"
                checked={col.visible}
                onChange={(e) => onChange(col.id, e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border text-primary"
              />
              {col.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
