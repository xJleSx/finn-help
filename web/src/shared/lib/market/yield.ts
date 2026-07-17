export function getYieldInfo(ytm: number, currentYield: number): {
  spread: number;
  aboveMarket: boolean;
} {
  const spread = ytm - currentYield;
  return {
    spread,
    aboveMarket: spread > 0,
  };
}
