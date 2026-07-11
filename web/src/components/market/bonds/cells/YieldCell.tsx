import { TrendingUp } from "lucide-react";
import { Bond } from "@/types/bond";

interface Props {
    bond: Bond;
}

export default function YieldCell({
    bond,
}: Props) {
    return (
        <div>
            <div className="flex items-center gap-2">
                <TrendingUp
                    className="h-4 w-4 text-emerald-500"
                />
                <span className="font-semibold">
                    {bond.yieldToMaturity.toFixed(2)}%
                </span>
            </div>
            <div className="text-xs text-muted-foreground">
                Купон {bond.couponYield.toFixed(2)}%
            </div>
        </div>
    );
}
