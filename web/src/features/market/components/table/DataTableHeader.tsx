import { flexRender, Table } from "@tanstack/react-table";
import { ArrowUpDown, ArrowUp, ArrowDown, ChevronsUpDown } from "lucide-react";

interface Props<TData> {
  table: Table<TData>;
}

function SortIcon({ direction }: { direction: false | "asc" | "desc" }) {
  if (direction === "asc") return <ArrowUp className="h-3 w-3" />;
  if (direction === "desc") return <ArrowDown className="h-3 w-3" />;
  return <ChevronsUpDown className="h-3 w-3 opacity-30" />;
}

export default function DataTableHeader<TData>({ table }: Props<TData>) {
  return (
    <thead className="sticky top-0 z-30">
      {table.getHeaderGroups().map((headerGroup) => (
        <tr key={headerGroup.id} className="border-b shadow-sm">
          {headerGroup.headers.map((header, index) => {
            const canSort = header.column.getCanSort();
            const sortDirection = header.column.getIsSorted();
            return (
              <th
                key={header.id}
                className={`px-4 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground whitespace-nowrap bg-background/95 backdrop-blur-md ${
                  index === 0 ? "sticky left-0 z-10 bg-background/95 backdrop-blur-md" : ""
                }`}
                style={{ width: header.getSize() }}
              >
                {canSort ? (
                  <div
                    className="inline-flex cursor-pointer select-none items-center gap-1"
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    <SortIcon direction={sortDirection} />
                  </div>
                ) : (
                  flexRender(header.column.columnDef.header, header.getContext())
                )}
              </th>
            );
          })}
        </tr>
      ))}
    </thead>
  );
}
