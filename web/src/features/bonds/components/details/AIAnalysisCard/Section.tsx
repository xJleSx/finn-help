import type { ReactNode } from "react";

interface Props {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
}

export default function Section({ title, icon, children }: Props) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        {icon && <span className="text-base">{icon}</span>}
        <h4 className="text-sm font-semibold text-foreground">{title}</h4>
      </div>
      {children}
    </div>
  );
}
