"use client";

import {
    ColumnDef,
    getCoreRowModel,
    getSortedRowModel,
    SortingState,
    useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";
import TableHeader from "./TableHeader";
import TableBody from "./TableBody";

interface Props<T> {
    data: T[];
    columns: ColumnDef<T>[];
    getRowLink?: (row: T) => string;
}

export default function Table<T>({
    data,
    columns,
    getRowLink,
}: Props<T>) {
    const [sorting, setSorting] = useState<SortingState>([]);

    const table = useReactTable({
        data,
        columns,
        state: { sorting },
        onSortingChange: setSorting,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
    });

    return (
        <div className="overflow-hidden rounded-2xl border bg-card">
            <table className="w-full">
                <TableHeader table={table} />
                <TableBody table={table} getRowLink={getRowLink} />
            </table>
        </div>
    );
}
