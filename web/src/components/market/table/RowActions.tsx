"use client";

import { MoreHorizontal, FileText, Briefcase, Star, Scale, ClipboardCopy } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

export interface RowActionsProps {
  onOpen?: () => void;
  onAddToPortfolio?: () => void;
  onFavorite?: () => void;
  onCompare?: () => void;
  onCopyIsin?: (() => void) | string;
}

export default function RowActions({
  onOpen,
  onAddToPortfolio,
  onFavorite,
  onCompare,
  onCopyIsin,
}: RowActionsProps) {
  const handleCopy = async () => {
    if (typeof onCopyIsin === "string") {
      try {
        await navigator.clipboard.writeText(onCopyIsin);
      } catch {
        // fallback silently
      }
    } else {
      onCopyIsin?.();
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex h-8 w-8 items-center justify-center rounded-md opacity-0 transition-opacity group-hover:opacity-100 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="h-4 w-4 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={4}
        className="z-50 min-w-[200px] rounded-xl border bg-card p-1 shadow-lg backdrop-blur-md"
        onClick={(e) => e.stopPropagation()}
      >
        {onOpen && (
          <DropdownMenuItem
            onSelect={onOpen}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <FileText className="h-4 w-4 text-muted-foreground" />
            Открыть
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator className="mx-2 my-1 h-px bg-border/50" />
        {onAddToPortfolio && (
          <DropdownMenuItem
            onSelect={onAddToPortfolio}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <Briefcase className="h-4 w-4 text-muted-foreground" />
            Добавить в портфель
          </DropdownMenuItem>
        )}
        {onFavorite && (
          <DropdownMenuItem
            onSelect={onFavorite}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <Star className="h-4 w-4 text-muted-foreground" />
            Добавить в избранное
          </DropdownMenuItem>
        )}
        {onCompare && (
          <DropdownMenuItem
            onSelect={onCompare}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <Scale className="h-4 w-4 text-muted-foreground" />
            Сравнить
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator className="mx-2 my-1 h-px bg-border/50" />
        {onCopyIsin && (
          <DropdownMenuItem
            onSelect={handleCopy}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <ClipboardCopy className="h-4 w-4 text-muted-foreground" />
            Скопировать ISIN
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
