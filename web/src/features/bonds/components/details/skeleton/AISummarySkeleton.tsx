export default function AISummarySkeleton() {
  return (
    <div className="space-y-5 rounded-xl border bg-card p-6 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-5 w-32 rounded bg-muted" />
          <div className="h-3 w-24 rounded bg-muted" />
        </div>
        <div className="flex gap-0.5">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="h-4 w-2 rounded-sm bg-muted" />
          ))}
        </div>
      </div>
      <div className="h-6 w-24 rounded-full bg-muted" />
      <div className="h-px bg-border/50" />
      <div className="space-y-2">
        <div className="h-4 w-16 rounded bg-muted" />
        <div className="h-3 w-full rounded bg-muted" />
        <div className="h-3 w-3/4 rounded bg-muted" />
      </div>
      <div className="h-px bg-border/50" />
      <div className="space-y-2">
        <div className="h-4 w-16 rounded bg-muted" />
        <div className="h-3 w-full rounded bg-muted" />
      </div>
      <div className="h-px bg-border/50" />
      <div className="space-y-2">
        <div className="h-4 w-32 rounded bg-muted" />
        <div className="flex gap-1">
          {Array.from({ length: 20 }).map((_, i) => (
            <div key={i} className="h-3 flex-1 rounded-sm bg-muted" />
          ))}
        </div>
      </div>
    </div>
  );
}
