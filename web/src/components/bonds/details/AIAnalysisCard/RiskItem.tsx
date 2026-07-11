interface Props {
  text: string;
}

export default function RiskItem({ text }: Props) {
  return (
    <div className="flex items-start gap-2 text-sm text-muted-foreground">
      <span className="mt-0.5 shrink-0 text-red-500">⚠</span>
      {text}
    </div>
  );
}
