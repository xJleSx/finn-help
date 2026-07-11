"use client";

import {
    flexRender,
    Table,
} from "@tanstack/react-table";

interface Props<T> {
    table: Table<T>;
}

export default function TableHeader<T>({
    table,
}: Props<T>) {
    return (
        <thead className="sticky top-0 bg-card">
            {table
                .getHeaderGroups()
                .map((headerGroup) => (
                    <tr key={headerGroup.id}>
                        {headerGroup.headers.map(
                            (header) => (
                                <th
                                    key={header.id}
                                    className="cursor-pointer border-b px-5 py-4 text-left text-sm font-semibold"
                                    onClick={header.column.getToggleSortingHandler()}
                                >
                                    {flexRender(
                                        header.column.columnDef.header,
                                        header.getContext()
                                    )}
                                </th>
                            )
                        )}
                    </tr>
                ))}
        </thead>
    );
}
