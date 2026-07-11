export default function CashFlowSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="mb-4 h-4 w-20 rounded bg-muted" />
      <div className="space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex gap-4">
            <div className="flex flex-col items-center">
              <div className="h-3 w-3 rounded-full bg-muted" />
              {i < 3 && <div className="mt-0.5 w-px flex-1 bg-muted" />}
            </div>
            <div className="mb-4 flex-1 rounded-lg border border-border bg-card/50 p-4">
              <div className="flex items-center justify-between">
                <div className="h-3 w-32 rounded bg-muted" />
                <div className="h-4 w-16 rounded bg-muted" />
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4 border-t border-border/50 pt-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <div className="h-3 w-16 rounded bg-muted" />
            <div className="h-5 w-12 rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
