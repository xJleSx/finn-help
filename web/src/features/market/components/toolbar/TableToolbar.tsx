"use client";

import type { ReactNode } from "react";

interface Props {
  search?: ReactNode;
  filters?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}

export default function TableToolbar({ search, filters, actions, children }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        {search}
        {filters}
      </div>
      <div className="flex items-center gap-2">
        {actions}
        {children}
      </div>
    </div>
  );
}
