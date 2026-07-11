interface Props {
    rating: string;
}

const COLORS: Record<string, string> = {
    AAA: "bg-emerald-500/15 text-emerald-500",
    "AA+": "bg-green-500/15 text-green-500",
    AA: "bg-lime-500/15 text-lime-500",
    A: "bg-yellow-500/15 text-yellow-500",
    BBB: "bg-orange-500/15 text-orange-500",
    NR: "bg-gray-500/15 text-gray-500",
};

export default function CreditRating({ rating }: Props) {
    const color = COLORS[rating] ?? COLORS.NR;
    return (
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${color}`}>
            {rating}
        </span>
    );
}
