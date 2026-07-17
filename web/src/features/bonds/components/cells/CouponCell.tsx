import { Bond } from "@/features/bonds/types/bond";

interface Props {
    bond: Bond;
}

export default function CouponCell({ bond }: Props) {
    return <>{bond.couponValue} ₽</>;
}
