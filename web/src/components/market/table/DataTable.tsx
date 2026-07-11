import { type DataTableProps } from "./types";
import DataTableHeader from "./DataTableHeader";
import DataTableBody from "./DataTableBody";
import DataTableLoading from "./DataTableLoading";

export default function DataTable<TData>({
  table,
  loading,
  emptyMessage = "Нет данных",
  className = "",
  onRowClick,
  getRatingColor,
  renderActions,
}: DataTableProps<TData>) {
  if (loading) {
    return (
      <div className={`overflow-hidden rounded-xl border bg-card ${className}`}>
        <DataTableLoading />
      </div>
    );
  }

  if (table.getRowModel().rows.length === 0) {
    return (
      <div className={`flex h-48 items-center justify-center rounded-xl border bg-card ${className}`}>
        <div className="text-center">
          <div className="text-2xl">📈</div>
          <div className="mt-2 text-sm font-medium text-foreground">Облигации не найдены</div>
          <div className="mt-1 text-xs text-muted-foreground">Попробуйте изменить фильтры</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-xl border bg-card ${className}`}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <DataTableHeader table={table} />
          <DataTableBody
            table={table}
            onRowClick={onRowClick}
            getRatingColor={getRatingColor}
            renderActions={renderActions}
          />
        </table>
      </div>
    </div>
  );
}
