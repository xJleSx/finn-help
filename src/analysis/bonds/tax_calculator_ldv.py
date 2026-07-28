from __future__ import annotations

from typing import Any

from src.config import TAX_RATES


def calc_tax_base(
    buy_price: float,
    sell_price: float,
    coupon_received: float,
    nkd_at_purchase: float,
    nkd_at_sale: float = 0.0,
    ldv_eligible: bool = False,
) -> dict[str, Any]:
    cap_gain = sell_price - buy_price
    coupon_taxable = coupon_received - nkd_at_purchase + max(0, nkd_at_sale - nkd_at_purchase)
    tax_base = cap_gain + coupon_taxable

    tax_rate = 0.0 if ldv_eligible else TAX_RATES.get("coupon_ndfl", 0.13)
    tax_due = tax_base * tax_rate if tax_base > 0 else 0.0

    return {
        "capitalGain": round(cap_gain, 2),
        "couponTaxable": round(coupon_taxable, 2),
        "taxBase": round(tax_base, 2),
        "taxRate": tax_rate,
        "taxDue": round(tax_due, 2),
        "ldvApplied": ldv_eligible,
        "note": (
            "ЛДВ: прирост капитала не облагается" if ldv_eligible
            else f"НДФЛ {tax_rate*100:.0f}% с налоговой базы"
        ),
    }


def check_ldv_eligibility(
    is_ofz: bool,
    purchase_date: str,
    years_held: float = 3.0,
    account_type: str = "broker",
    is_quasi_gov: bool = False,
) -> dict[str, Any]:
    eligible = False
    reasons: list[str] = []

    if account_type not in ("broker", "iis_type_a", "iis_type_b", "iis_type_3"):
        reasons.append(f"Тип счёта «{account_type}» — льгота не применима")
    elif account_type in ("iis_type_a", "iis_type_b", "iis_type_3"):
        reasons.append(f"ИИС ({account_type}) — льгота применима")
    elif not is_ofz and not is_quasi_gov:
        reasons.append("Не ОФЗ/субфедеральная — льгота только для ОФЗ")
    elif years_held < 3:
        reasons.append(f"Срок владения {years_held:.1f} лет < 3 лет — льгота не применима")
    else:
        eligible = True
        reasons.append("ЛДВ применима: ОФЗ + 3+ года + брокерский счёт")

    return {
        "ldvEligible": eligible,
        "reasons": reasons,
        "yearsHeld": round(years_held, 1),
        "accountType": account_type,
        "bondType": "ofz" if is_ofz else ("quasi_gov" if is_quasi_gov else "corporate"),
        "taxRateWithoutLDV": TAX_RATES.get("capital_gains_ndfl", 0.13),
        "taxRateWithLDV": 0.0,
    }
