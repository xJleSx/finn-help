import { ColumnDef } from "@tanstack/react-table";
import { Bond } from "@/types/bond";
import { COLUMN_WIDTHS } from "@/lib/table/columnWidths";
import InstrumentName from "../cells/InstrumentName";
import Price from "../cells/Price";
import Profit from "../cells/Profit";
import AIScore from "../cells/AIScore";
import CreditRating from "../cells/CreditRating";
import DateWithCountdown from "../cells/DateWithCountdown";
import YieldCell from "./cells/YieldCell";
import CouponCell from "./cells/CouponCell";
import DurationCell from "./cells/DurationCell";
import RedemptionCell from "./cells/RedemptionCell";

export const columns: ColumnDef<Bond>[] = [
  {
    accessorKey: "name",
    header: "Облигация",
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
    accessorKey: "currentPrice",
    header: "Цена",
    size: COLUMN_WIDTHS.price,
    cell: ({ row }) => (
      <Price
        price={row.original.currentPrice}
        purchasePrice={row.original.purchasePrice}
      />
    ),
  },
  {
    accessorKey: "yieldToMaturity",
    header: "Доходность",
    size: COLUMN_WIDTHS.yield,
    cell: ({ row }) => <YieldCell bond={row.original} />,
  },
  {
    accessorKey: "couponValue",
    header: "Купон",
    size: COLUMN_WIDTHS.coupon,
    cell: ({ row }) => <CouponCell bond={row.original} />,
  },
  {
    accessorKey: "nextCouponDate",
    header: "Следующий купон",
    size: COLUMN_WIDTHS.couponDate,
    cell: ({ row }) => (
      <DateWithCountdown date={new Date(row.original.nextCouponDate)} />
    ),
  },
  {
    accessorKey: "rating",
    header: "Рейтинг",
    size: COLUMN_WIDTHS.rating,
    cell: ({ row }) => <CreditRating rating={row.original.rating} />,
  },
  {
    accessorKey: "unrealizedPnL",
    header: "Прибыль",
    size: COLUMN_WIDTHS.profit,
    cell: ({ row }) => {
      const bond = row.original;
      const invested = bond.invested || 1;
      const percent = ((bond.currentValue - invested) / invested) * 100;
      return <Profit amount={bond.unrealizedPnL} percent={percent} />;
    },
  },
  {
    accessorKey: "aiScore",
    header: "AI",
    size: COLUMN_WIDTHS.ai,
    cell: ({ row }) => <AIScore score={row.original.aiScore} />,
  },
  {
    accessorKey: "duration",
    header: "Дюрация",
    size: COLUMN_WIDTHS.duration,
    cell: ({ row }) => <DurationCell bond={row.original} />,
  },
  {
    accessorKey: "expectedRedemptionValue",
    header: "Погашение",
    size: COLUMN_WIDTHS.redemption,
    cell: ({ row }) => <RedemptionCell bond={row.original} />,
  },
];
