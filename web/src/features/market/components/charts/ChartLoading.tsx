export default function ChartLoading() {
  return (
    <div className="flex h-[320px] items-center justify-center rounded-lg bg-muted/30">
      <div className="flex flex-col items-center gap-2">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-xs text-muted-foreground">Загрузка графика...</span>
      </div>
    </div>
  );
}
