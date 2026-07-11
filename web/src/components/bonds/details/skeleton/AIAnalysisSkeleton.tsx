export default function AIAnalysisSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="mb-4 h-4 w-20 rounded bg-muted" />
      <div className="space-y-5">
        <div className="space-y-2">
          <div className="h-3 w-full rounded bg-muted" />
          <div className="h-3 w-5/6 rounded bg-muted" />
        </div>
        <div className="space-y-2">
          <div className="h-4 w-40 rounded bg-muted" />
          <div className="h-3 w-full rounded bg-muted" />
          <div className="h-3 w-3/4 rounded bg-muted" />
        </div>
        <div className="space-y-2">
          <div className="h-4 w-24 rounded bg-muted" />
          <div className="h-3 w-full rounded bg-muted" />
          <div className="h-3 w-2/3 rounded bg-muted" />
        </div>
        <div className="h-px bg-border/50" />
        <div className="flex items-center justify-between rounded-lg border bg-card/50 p-4">
          <div className="space-y-2">
            <div className="h-3 w-12 rounded bg-muted" />
            <div className="h-5 w-24 rounded bg-muted" />
          </div>
          <div className="flex gap-0.5">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="h-4 w-2 rounded-sm bg-muted" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
