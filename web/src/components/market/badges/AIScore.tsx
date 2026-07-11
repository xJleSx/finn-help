interface Props {
    score: number;
}

export default function AIScore({ score }: Props) {
    let color = "text-red-500";
    if (score > 85) color = "text-emerald-500";
    else if (score > 70) color = "text-yellow-500";

    return (
        <span className={`font-bold ${color}`}>
            {score}/100
        </span>
    );
}
