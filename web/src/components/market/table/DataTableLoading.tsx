const SKELETON_ROWS = 6;

const COLUMNS = [
  { width: "w-[320px]" },
  { width: "w-[150px]" },
  { width: "w-[140px]" },
  { width: "w-[150px]" },
  { width: "w-[180px]" },
  { width: "w-[120px]" },
  { width: "w-[190px]" },
  { width: "w-[170px]" },
  { width: "w-[130px]" },
  { width: "w-[170px]" },
];

export default function DataTableLoading() {
  return (
    <div className="divide-y divide-border/50">
      {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
        <div key={i} className="flex h-[76px] animate-pulse items-center px-4 gap-4">
          <div className="flex items-center gap-3 min-w-0" style={{ width: 320 }}>
            <div className="h-10 w-10 shrink-0 rounded-lg bg-muted" />
            <div className="space-y-2 flex-1">
              <div className="h-3 w-32 rounded bg-muted" />
              <div className="h-2 w-24 rounded bg-muted" />
            </div>
          </div>
          {COLUMNS.slice(1).map((col, j) => (
            <div key={j} className={`h-3 rounded bg-muted ${col.width}`} />
          ))}
        </div>
      ))}
    </div>
  );
}
