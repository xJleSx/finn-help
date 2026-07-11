interface Props {
  price: number;
  purchasePrice?: number;
  currency?: string;
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  RUB: "₽",
  USD: "$",
  EUR: "€",
};

export default function Price({ price, purchasePrice, currency = "RUB" }: Props) {
  const symbol = CURRENCY_SYMBOLS[currency] ?? currency;
  const diff = purchasePrice != null ? price - purchasePrice : null;
  const positive = diff != null && diff >= 0;

  return (
    <div>
      <div className="font-semibold tabular-nums">
        {price.toLocaleString()} {symbol}
      </div>
      {purchasePrice != null && (
        <div className={`text-xs tabular-nums ${positive ? "text-emerald-500" : "text-red-500"}`}>
          Покупка {purchasePrice.toLocaleString()} {symbol}
        </div>
      )}
    </div>
  );
}
