import { ReactNode } from "react";
import { Table } from "@tanstack/react-table";

export interface DataTableProps<TData> {
  table: Table<TData>;
  loading?: boolean;
  emptyMessage?: string;
  className?: string;
  onRowClick?: (row: TData) => void;
  getRatingColor?: (row: TData) => string;
  renderActions?: (row: TData) => ReactNode;
}

export interface DataTableRowProps<TData> {
  row: TData;
  onClick?: () => void;
  ratingColor?: string;
  renderActions?: (row: TData) => ReactNode;
}

export interface DataTableBodyProps<TData> {
  table: Table<TData>;
  loading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: TData) => void;
  getRatingColor?: (row: TData) => string;
  renderActions?: (row: TData) => ReactNode;
}
