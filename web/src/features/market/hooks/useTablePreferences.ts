"use client";

import { useState, useCallback, useEffect } from "react";
import type { TableDensity } from "@/features/market/components/table/types";

const STORAGE_KEY = "table-preferences";

interface TablePreferences {
  density: TableDensity;
  columnOrder: Record<string, string[]>;
  columnVisibility: Record<string, Record<string, boolean>>;
  columnPinning: Record<string, Record<string, string[]>>;
}

function loadPreferences(): Partial<TablePreferences> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function savePreferences(prefs: Partial<TablePreferences>) {
  try {
    const existing = loadPreferences();
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...existing, ...prefs }));
  } catch {
    // localStorage unavailable
  }
}

export function useTablePreferences(tableId: string) {
  const stored = loadPreferences();

  const [density, setDensityState] = useState<TableDensity>(
    stored.density ?? "comfortable"
  );

  const [columnVisibility, setColumnVisibilityState] = useState<
    Record<string, boolean>
  >(stored.columnVisibility?.[tableId] ?? {});

  const setDensity = useCallback((d: TableDensity) => {
    setDensityState(d);
    savePreferences({ density: d });
  }, []);

  const setColumnVisibility = useCallback(
    (id: string, visible: boolean) => {
      setColumnVisibilityState((prev) => {
        const next = { ...prev, [id]: visible };
        savePreferences({
          columnVisibility: { ...stored.columnVisibility, [tableId]: next },
        });
        return next;
      });
    },
    [tableId, stored.columnVisibility]
  );

  return { density, setDensity, columnVisibility, setColumnVisibility };
}
