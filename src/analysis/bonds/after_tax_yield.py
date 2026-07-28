from __future__ import annotations

from typing import Any, Optional

from src.config import MOEX_EXCHANGE_FEE_PCT, TAX_RATES
from src.trading.broker_commissions import get_commission_config


def calc_after_tax_yield(
    ytm_gross: float,
    clean_price: float = 100.0,
    accrued_interest: float = 0.0,
    nominal: float = 1000.0,
    broker_key: str = "tbank",
    inflation_forecast: Optional[float] = None,
    account_type: str = "broker",
    years_to_maturity: float = 1.0,
    ldv_eligible: bool = False,
    spread_pct: float = 0.3,
) -> dict[str, Any]:
    dirty_price = clean_price + accrued_interest

    coupon_tax_rate = TAX_RATES.get("coupon_ndfl", 0.13)
    cap_gains_tax_rate = TAX_RATES.get("capital_gains_ndfl", 0.13) if not ldv_eligible else 0.0

    ytm_after_coupon_tax = ytm_gross * (1 - coupon_tax_rate)

    capital_gain_pct = (nominal - dirty_price) / dirty_price * 100 if dirty_price > 0 else 0
    annualized_cap_gain = capital_gain_pct / years_to_maturity if years_to_maturity > 0 else 0
    cap_gain_after_tax = annualized_cap_gain * (1 - cap_gains_tax_rate)

    commission_config = get_commission_config(broker_key)
    broker_commission_pct = commission_config.get("commission_pct", 0.025)
    total_commission_pct = (broker_commission_pct * 2) + MOEX_EXCHANGE_FEE_PCT

    ytm_after_costs = ytm_after_coupon_tax + cap_gain_after_tax - total_commission_pct - spread_pct

    real_yield = None
    if inflation_forecast is not None:
        real_yield = ((1 + ytm_after_costs / 100) / (1 + inflation_forecast / 100) - 1) * 100

    return {
        "ytmGross": round(ytm_gross, 2),
        "dirtyPrice": round(dirty_price, 2),
        "accruedInterest": round(accrued_interest, 2),
        "ytmAfterCouponTax": round(ytm_after_coupon_tax, 2),
        "capitalGainAnnualizedPct": round(annualized_cap_gain, 2),
        "capitalGainAfterTax": round(cap_gain_after_tax, 2),
        "brokerCommissionPct": round(total_commission_pct, 3),
        "spreadCostPct": round(spread_pct, 2),
        "ytmAfterCosts": round(ytm_after_costs, 2),
        "inflationForecast": round(inflation_forecast, 2) if inflation_forecast is not None else None,
        "realYield": round(real_yield, 2) if real_yield is not None else None,
        "accountType": account_type,
        "ldvEligible": ldv_eligible,
    }
