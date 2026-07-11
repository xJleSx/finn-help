import { Row, flexRender } from "@tanstack/react-table";
import type { ReactNode } from "react";

interface Props<TData> {
  row: Row<TData>;
  onClick?: () => void;
  ratingColor?: string;
  renderActions?: (row: TData) => ReactNode;
}

export default function DataTableRow<TData>({
  row,
  onClick,
  ratingColor,
  renderActions,
}: Props<TData>) {
  const visibleCells = row.getVisibleCells();

  return (
    <tr
      className="group relative transition-colors duration-150 hover:bg-accent/40 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary data-[state=selected]:bg-primary/5"
      onClick={onClick}
      tabIndex={0}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {ratingColor && (
        <td className="relative w-0 p-0">
          <span
            className={`absolute left-0 top-0 h-full w-1 rounded-r-full ${ratingColor}`}
          />
        </td>
      )}
      {visibleCells.map((cell, index) => (
        <td
          key={cell.id}
          className={`px-4 py-3 h-[76px] align-middle ${
            index === 0 ? "sticky left-0 z-10 bg-background" : ""
          }`}
        >
          <div className="relative flex items-center gap-2">
            <div className="flex-1 min-w-0">
              {flexRender(cell.column.columnDef.cell, cell.getContext())}
            </div>
            {index === visibleCells.length - 1 && renderActions && (
              <div className="shrink-0">
                {renderActions(row.original)}
              </div>
            )}
          </div>
        </td>
      ))}
    </tr>
  );
}
