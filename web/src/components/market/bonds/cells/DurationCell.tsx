import { Bond } from "@/types/bond";

interface Props {
    bond: Bond;
}

export default function DurationCell({ bond }: Props) {
    return <span>{bond.duration.toFixed(1)} г</span>;
}
