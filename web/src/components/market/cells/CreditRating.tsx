import { getRatingColor } from "@/lib/market/creditRating";

interface Props {
  rating: string;
}

export default function CreditRating({ rating }: Props) {
  const color = getRatingColor(rating);

  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold tabular-nums ${color.replace("bg-", "bg-").replace("500", "500/15")} ${color.replace("bg-", "text-")}`}
    >
      {rating}
    </span>
  );
}
