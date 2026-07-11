import type { DataTableBodyProps } from "./types";
import DataTableRow from "./DataTableRow";

export default function DataTableBody<TData>({
  table,
  onRowClick,
  getRatingColor,
  renderActions,
}: DataTableBodyProps<TData>) {
  const rows = table.getRowModel().rows;

  return (
    <tbody className="divide-y divide-border/50">
      {rows.map((row) => (
        <DataTableRow
          key={row.id}
          row={row}
          onClick={onRowClick ? () => onRowClick(row.original) : undefined}
          ratingColor={getRatingColor?.(row.original)}
          renderActions={renderActions}
        />
      ))}
    </tbody>
  );
}
