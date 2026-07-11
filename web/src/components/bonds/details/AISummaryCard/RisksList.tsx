interface Props {
  risks: string[];
}

export default function RisksList({ risks }: Props) {
  if (risks.length === 0) return null;

  return (
    <div>
      <div className="mb-2 text-sm font-medium text-red-500">⚠ Риски</div>
      <ul className="space-y-1">
        {risks.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
            <span className="mt-1 block h-1 w-1 shrink-0 rounded-full bg-red-500" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
