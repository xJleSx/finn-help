import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
}

export default function OverviewGrid({ children }: Props) {
  return (
    <div className="grid grid-cols-2 gap-6 xl:grid-cols-3">
      {children}
    </div>
  );
}
