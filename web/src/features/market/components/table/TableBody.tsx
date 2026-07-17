"use client";

import { Table } from "@tanstack/react-table";
import TableRow from "./TableRow";

interface Props<T> {
    table: Table<T>;
    getRowLink?: (row: T) => string;
}

export default function TableBody<T>({
    table,
    getRowLink,
}: Props<T>) {
    return (
        <tbody>
            {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} row={row} getRowLink={getRowLink} />
            ))}
        </tbody>
    );
}
