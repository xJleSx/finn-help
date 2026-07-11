interface Props {
    price: number;
}

export default function Price({ price }: Props) {
    return (
        <span className="font-mono text-white">
            {price.toFixed(2)} ₽
        </span>
    );
}
