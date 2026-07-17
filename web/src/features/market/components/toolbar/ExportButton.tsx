"use client";

import { Download } from "lucide-react";

interface Props {
  onExport: () => void;
  label?: string;
}

export default function ExportButton({ onExport, label = "CSV" }: Props) {
  return (
    <button
      type="button"
      onClick={onExport}
      className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
    >
      <Download className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
