"use client";

import {
    Row,
    flexRender,
} from "@tanstack/react-table";
import { useRouter } from "next/navigation";

interface Props<T> {
    row: Row<T>;
    getRowLink?: (row: T) => string;
}

export default function TableRow<T>({
    row,
    getRowLink,
}: Props<T>) {
    const router = useRouter();

    const handleClick = getRowLink
        ? () => router.push(getRowLink(row.original))
        : undefined;

    return (
        <tr
            className="cursor-pointer border-b transition-all duration-200 hover:scale-[1.002] hover:shadow-md"
            onClick={handleClick}
        >
            {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-5 py-4">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
            ))}
        </tr>
    );
}
