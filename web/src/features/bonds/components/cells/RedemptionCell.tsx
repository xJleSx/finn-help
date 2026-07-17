import { Bond } from "@/features/bonds/types/bond";

interface Props {
    bond: Bond;
}

export default function RedemptionCell({ bond }: Props) {
    const date = new Date(bond.maturityDate);
    const formatted = date.toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "short",
        year: "numeric",
    });
    return (
        <div>
            <div className="font-semibold">{bond.expectedRedemptionValue.toLocaleString()} ₽</div>
            <div className="text-xs text-muted-foreground">{formatted}</div>
        </div>
    );
}
