import type { ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

export default function SectionCard({ title, children, action, className = "" }: Props) {
  return (
    <div className={`rounded-xl border bg-card p-6 ${className}`}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h3>
        {action && <div className="flex items-center">{action}</div>}
      </div>
      {children}
    </div>
  );
}
