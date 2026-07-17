"use client";

import {
  useReactTable,
  getCoreRowModel,
  type ColumnDef,
} from "@tanstack/react-table";
import DataTable from "@/features/market/components/table/DataTable";
import InstrumentName from "@/features/market/components/cells/InstrumentName";
import Price from "@/features/market/components/cells/Price";
import Profit from "@/features/market/components/cells/Profit";
import AIScore from "@/features/market/components/cells/AIScore";
import { formatNumber } from "@/lib/format";
import type { BondPosition } from "@/features/portfolio/types/bond-position";

interface Props {
  positions: BondPosition[];
  onRowClick?: (position: BondPosition) => void;
}

const COLUMN_WIDTHS = {
  instrument: 320,
  quantity: 120,
  price: 150,
  value: 140,
  profit: 170,
  ytm: 120,
  ai: 190,
  allocation: 140,
};

const columns: ColumnDef<BondPosition>[] = [
  {
    accessorKey: "name",
    header: "Инструмент",
    size: COLUMN_WIDTHS.instrument,
    cell: ({ row }) => (
      <InstrumentName
        name={row.original.name}
        ticker={row.original.ticker}
        subtitle={row.original.issuer}
        isin={row.original.isin}
      />
    ),
  },
  {
    accessorKey: "quantity",
    header: "Количество",
    size: COLUMN_WIDTHS.quantity,
    cell: ({ row }) => (
      <div className="font-semibold tabular-nums text-foreground">
        {formatNumber(row.original.quantity, 0)}
      </div>
    ),
  },
  {
    accessorKey: "avgPrice",
    header: "Средняя цена",
    size: COLUMN_WIDTHS.price,
    cell: ({ row }) => <Price price={row.original.avgPrice} />,
  },
  {
    accessorKey: "currentPrice",
    header: "Текущая цена",
    size: COLUMN_WIDTHS.price,
    cell: ({ row }) => (
      <Price price={row.original.currentPrice} purchasePrice={row.original.avgPrice} />
    ),
  },
  {
    accessorKey: "totalValue",
    header: "Стоимость",
    size: COLUMN_WIDTHS.value,
    cell: ({ row }) => (
      <div className="font-semibold tabular-nums text-foreground">
        {row.original.totalValue.toLocaleString()} ₽
      </div>
    ),
  },
  {
    accessorKey: "profit",
    header: "Доход",
    size: COLUMN_WIDTHS.profit,
    cell: ({ row }) => (
      <Profit amount={row.original.profit} percent={row.original.profitPercent} />
    ),
  },
  {
    accessorKey: "ytm",
    header: "YTM",
    size: COLUMN_WIDTHS.ytm,
    cell: ({ row }) => (
      <div className="font-semibold tabular-nums text-foreground">
        {row.original.ytm.toFixed(2)}%
      </div>
    ),
  },
  {
    accessorKey: "aiScore",
    header: "AI",
    size: COLUMN_WIDTHS.ai,
    cell: ({ row }) => <AIScore score={row.original.aiScore} />,
  },
  {
    accessorKey: "allocation",
    header: "Доля",
    size: COLUMN_WIDTHS.allocation,
    cell: ({ row }) => {
      const pct = row.original.allocation;
      return (
        <div className="flex items-center gap-2">
          <div className="h-2 w-16 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs font-semibold tabular-nums text-foreground">
            {pct.toFixed(1)}%
          </span>
        </div>
      );
    },
  },
];

export default function PortfolioTable({ positions, onRowClick }: Props) {
  const table = useReactTable({
    data: positions,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return <DataTable table={table} onRowClick={onRowClick} />;
}
