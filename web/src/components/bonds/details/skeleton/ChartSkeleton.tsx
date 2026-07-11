export default function ChartSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="mb-4 flex items-center justify-between">
        <div className="h-4 w-12 rounded bg-muted" />
        <div className="flex gap-1">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-6 w-10 rounded-md bg-muted" />
          ))}
        </div>
      </div>
      <div className="h-[320px] rounded-lg bg-muted" />
      <div className="mt-4 flex gap-5 border-t border-border/50 pt-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="h-4 w-4 rounded bg-muted" />
            <div className="h-4 w-20 rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
