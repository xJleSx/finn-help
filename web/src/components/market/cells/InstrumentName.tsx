import { ReactNode } from "react";

interface Props {
  name: string;
  ticker: string;
  icon?: ReactNode;
  logo?: string;
  subtitle?: string;
  isin?: string;
}

export default function InstrumentName({ name, ticker, icon, logo, subtitle, isin }: Props) {
  return (
    <div className="flex items-center gap-3 min-h-[64px]">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
        {logo ? (
          <img src={logo} alt="" className="h-6 w-6 rounded" />
        ) : icon ? (
          icon
        ) : (
          <span className="text-sm font-bold text-primary">{ticker[0]}</span>
        )}
      </div>
      <div className="min-w-0">
        <div className="font-semibold leading-tight text-foreground truncate">{name}</div>
        {subtitle && <div className="text-sm text-muted-foreground truncate">{subtitle}</div>}
        {isin && <div className="text-xs text-muted-foreground truncate">{isin}</div>}
      </div>
    </div>
  );
}
