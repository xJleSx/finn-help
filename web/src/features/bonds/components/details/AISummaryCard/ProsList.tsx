interface Props {
  items: string[];
}

export default function ProsList({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <div>
      <div className="mb-2 text-sm font-medium text-emerald-500">✔ Плюсы</div>
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
            <span className="mt-1 block h-1 w-1 shrink-0 rounded-full bg-emerald-500" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
