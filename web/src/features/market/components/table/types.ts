import { ReactNode } from "react";
import { Table } from "@tanstack/react-table";

export type TableDensity = "compact" | "comfortable" | "spacious";

const ROW_HEIGHTS: Record<TableDensity, string> = {
  compact: "h-[52px] py-2",
  comfortable: "h-[64px] py-3",
  spacious: "h-[88px] py-5",
};

export function getRowHeightClass(density: TableDensity): string {
  return ROW_HEIGHTS[density];
}

export interface DataTableProps<TData> {
  table: Table<TData>;
  loading?: boolean;
  emptyMessage?: string;
  className?: string;
  onRowClick?: (row: TData) => void;
  getRatingColor?: (row: TData) => string;
  renderActions?: (row: TData) => ReactNode;
  density?: TableDensity;
}

export interface DataTableRowProps<TData> {
  row: TData;
  onClick?: () => void;
  ratingColor?: string;
  renderActions?: (row: TData) => ReactNode;
  density?: TableDensity;
}

export interface DataTableBodyProps<TData> {
  table: Table<TData>;
  loading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: TData) => void;
  getRatingColor?: (row: TData) => string;
  renderActions?: (row: TData) => ReactNode;
  density?: TableDensity;
}
