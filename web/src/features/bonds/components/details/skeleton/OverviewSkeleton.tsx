export default function OverviewSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="mb-6 h-4 w-36 rounded bg-muted" />
      <div className="grid grid-cols-2 gap-6 xl:grid-cols-3">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <div className="h-3 w-20 rounded bg-muted" />
            <div className="h-5 w-24 rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
