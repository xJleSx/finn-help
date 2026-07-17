export default function MetricsSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="mb-6 h-4 w-44 rounded bg-muted" />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-3">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="space-y-2 rounded-lg border bg-card/50 p-4">
            <div className="h-3 w-24 rounded bg-muted" />
            <div className="h-7 w-16 rounded bg-muted" />
            <div className="h-3 w-20 rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
