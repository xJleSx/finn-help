import type { CashFlowItemData } from "@/types/cash-flow";
import CashFlowItem from "./CashFlowItem";

interface Props {
  items: CashFlowItemData[];
}

export default function CashFlowTimeline({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <div className="py-2">
      {items.map((item, i) => (
        <CashFlowItem key={item.id} item={item} isLast={i === items.length - 1} />
      ))}
    </div>
  );
}
