export default function CouponSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="mb-4 h-4 w-44 rounded bg-muted" />
      <div className="space-y-3">
        <div className="flex items-center gap-4 border-b border-border/50 pb-3">
          <div className="h-3 w-24 rounded bg-muted" />
          <div className="h-3 w-16 rounded bg-muted" />
          <div className="h-3 w-20 rounded bg-muted" />
        </div>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 py-2">
            <div className="h-3 w-24 rounded bg-muted" />
            <div className="h-3 w-16 rounded bg-muted" />
            <div className="h-5 w-20 rounded-full bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
