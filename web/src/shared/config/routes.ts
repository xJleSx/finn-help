export const ROUTES = {
  HOME: "/",
  LOGIN: "/login",
  REGISTER: "/register",
  DASHBOARD: "/dashboard",
  INSTRUMENTS: "/instruments",
  BONDS: "/instruments/bonds",
  BOND_DETAIL: (ticker: string) => `/instruments/bonds/${ticker}`,
  PORTFOLIO: "/portfolio",
  PORTFOLIO_BONDS: "/portfolio/bonds",
  ALERTS: "/alerts",
  PAPER: "/paper",
} as const;
