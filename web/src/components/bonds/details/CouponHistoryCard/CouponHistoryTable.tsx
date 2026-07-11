"use client";

import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import type { CouponPayment } from "@/types/coupon";
import DataTable from "@/components/market/table/DataTable";
import CouponStatusBadge from "./CouponStatusBadge";

interface Props {
  payments: CouponPayment[];
}

const columns: ColumnDef<CouponPayment>[] = [
  {
    accessorKey: "date",
    header: "Дата",
    size: 160,
    cell: ({ row }) =>
      new Date(row.original.date).toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }),
  },
  {
    accessorKey: "amount",
    header: "Сумма",
    size: 140,
    cell: ({ row }) => `${row.original.amount.toLocaleString("ru-RU", { minimumFractionDigits: 2 })} ₽`,
  },
  {
    accessorKey: "status",
    header: "Статус",
    size: 140,
    cell: ({ row }) => <CouponStatusBadge status={row.original.status} />,
  },
];

export default function CouponHistoryTable({ payments }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "date", desc: true }]);

  const table = useReactTable({
    data: payments,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return <DataTable table={table} />;
}
