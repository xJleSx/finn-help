interface Props {
    value: number;
}

export default function Profit({ value }: Props) {
    const positive = value >= 0;
    return (
        <span
            className={
                positive
                    ? "font-semibold text-emerald-500"
                    : "font-semibold text-red-500"
            }
        >
            {positive ? "+" : ""}
            {value.toLocaleString()} ₽
        </span>
    );
}
