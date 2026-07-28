from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np


def coupon_period_to_frequency(coupon_period_days: int | None) -> int:
    if coupon_period_days is None or coupon_period_days <= 0:
        return 2
    if coupon_period_days <= 35:
        return 12
    if coupon_period_days <= 95:
        return 4
    if coupon_period_days <= 200:
        return 2
    return 1


def compute_current_yield(
    coupon_rate: float,
    clean_price_pct: float,
    nominal: float = 100.0,
) -> float:
    if clean_price_pct <= 0:
        return 0.0
    annual_coupon = (coupon_rate / 100) * nominal
    clean_rub = clean_price_pct / 100 * nominal
    return round(annual_coupon / clean_rub * 100, 2)


def compute_accrued_interest(
    coupon_rate: float,
    nominal: float,
    last_coupon_date: date,
    settlement_date: Optional[date] = None,
    coupon_period_days: int = 182,
    next_coupon_date: Optional[date] = None,
) -> float:
    if coupon_rate <= 0 or nominal <= 0:
        return 0.0
    settlement = settlement_date or date.today()
    days_since_coupon = (settlement - last_coupon_date).days
    if days_since_coupon <= 0:
        return 0.0
    period_length = coupon_period_days
    if next_coupon_date is not None:
        period_length = (next_coupon_date - last_coupon_date).days
        if period_length <= 0:
            period_length = coupon_period_days
    daily_coupon = (coupon_rate / 100) * nominal / period_length
    return round(daily_coupon * days_since_coupon, 2)


def clean_price_to_dirty(clean_price_pct: float, nominal: float, accrued_interest: float) -> float:
    clean_rub = clean_price_pct / 100 * nominal
    return clean_rub + accrued_interest


def compute_modified_duration(macaulay_duration: float, ytm: float, frequency: int) -> float:
    if macaulay_duration <= 0:
        return 0.0
    return round(macaulay_duration / (1 + ytm / 100 / frequency), 4)


def compute_floater_duration(
    years_to_next_reset: float,
    frequency: int = 2,
) -> float:
    if years_to_next_reset <= 0:
        return 0.0
    return round(years_to_next_reset + 0.5 / frequency, 4)


def put_exercise_probability(
    ytm_to_maturity: Optional[float] = None,
    ytm_to_put: Optional[float] = None,
    coupon_rate: Optional[float] = None,
    ytm: Optional[float] = None,
) -> float:
    if ytm_to_maturity is not None and ytm_to_put is not None:
        if ytm_to_maturity < ytm_to_put:
            return 0.8
        if abs(ytm_to_maturity - ytm_to_put) < 0.5:
            return 0.5
        return 0.2
    if coupon_rate is not None and ytm is not None:
        spread = ytm - coupon_rate
        if spread > 2.0:
            return 0.8
        if spread > 0.5:
            return 0.5
        return 0.2
    return 0.3


def compute_put_adjusted_duration(
    macaulay_duration: float,
    years_to_maturity: float,
    years_to_put: Optional[float] = None,
    p_exercise: float = 0.3,
) -> float:
    if years_to_put is None or years_to_put <= 0:
        return macaulay_duration
    if years_to_put >= years_to_maturity:
        return macaulay_duration
    d_put = years_to_put * macaulay_duration / years_to_maturity if years_to_maturity > 0 else years_to_put
    d_mat = macaulay_duration
    return round(p_exercise * d_put + (1 - p_exercise) * d_mat, 4)


def compute_duration(
    coupon_type: Optional[str] = None,
    years_to_maturity: float = 0.0,
    coupon_rate: float = 0.0,
    ytm: float = 0.0,
    frequency: int = 2,
    nominal: float = 100.0,
    has_put: bool = False,
    years_to_put: Optional[float] = None,
    years_to_next_reset: Optional[float] = None,
    p_exercise: Optional[float] = None,
) -> dict[str, float]:
    base_macaulay = None
    result = {}
    floater_types = {"FLOAT", "FRN", "ПК", "FLT"}
    if coupon_type and coupon_type.upper() in floater_types:
        reset = years_to_next_reset if years_to_next_reset is not None else years_to_maturity
        md = compute_floater_duration(reset, frequency)
        result["macaulayDuration"] = md
        result["modifiedDuration"] = round(md / (1 + ytm / 100 / frequency), 4) if ytm > 0 else md
        result["durationType"] = "floater"
        return result

    if has_put and years_to_put is not None and years_to_put > 0:
        base_macaulay = _approx_macaulay(coupon_rate, ytm, years_to_maturity, frequency, nominal)
    else:
        base_macaulay = _approx_macaulay(coupon_rate, ytm, years_to_maturity, frequency, nominal)
    if base_macaulay is None or base_macaulay <= 0:
        return {"macaulayDuration": 0.0, "modifiedDuration": 0.0}

    if has_put and years_to_put is not None and years_to_put > 0:
        if p_exercise is None:
            p_exercise = put_exercise_probability(coupon_rate=coupon_rate, ytm=ytm)
        adj = compute_put_adjusted_duration(base_macaulay, years_to_maturity, years_to_put, p_exercise)
        result["macaulayDuration"] = adj
        result["modifiedDuration"] = round(adj / (1 + ytm / 100 / frequency), 4) if ytm > 0 else adj
        result["durationType"] = "put_adjusted"
        return result

    mod_dur = base_macaulay / (1 + ytm / 100 / frequency) if ytm > 0 else base_macaulay
    result["macaulayDuration"] = round(base_macaulay, 4)
    result["modifiedDuration"] = round(mod_dur, 4)
    result["durationType"] = "standard"
    return result


def compute_convexity(
    coupon_rate: float,
    ytm: float,
    years_to_maturity: float,
    frequency: int = 2,
    nominal: float = 1000.0,
    price: Optional[float] = None,
) -> float:
    if ytm <= 0 or years_to_maturity <= 0:
        return 0.0
    if price is None:
        price = nominal
    rate = coupon_rate / 100
    y = ytm / 100
    n = int(years_to_maturity * frequency)
    if n <= 0:
        return 0.0
    c = rate * nominal / frequency
    t = np.arange(1, n + 1)
    cf = np.full(n, c)
    cf[-1] += nominal
    df = (1 + y / frequency) ** -t
    weighted_pv = cf * df * (t / frequency) ** 2
    pv_total = np.sum(cf * df)
    if pv_total <= 0:
        return 0.0
    convexity = np.sum(weighted_pv) / pv_total
    return round(float(convexity), 4)


def ytm_solver(
    price_pct: float,
    coupon_rate: float,
    years_to_maturity: float,
    nominal: float = 100.0,
    frequency: int = 2,
    guess: Optional[float] = None,
    max_iter: int = 100,
    tol: float = 1e-8,
    use_brent: bool = False,
) -> Optional[float]:
    if years_to_maturity <= 0 or price_pct <= 0:
        return None
    price = price_pct / 100 * nominal
    rate = coupon_rate / 100
    n = int(years_to_maturity * frequency)
    if n <= 0:
        return None
    coupon = rate * nominal / frequency

    if guess is None:
        coupon_yield = (coupon * frequency) / nominal * 100
        cap_loss = (nominal - price) / years_to_maturity / ((nominal + price) / 2) * 100
        guess = max(0.001, coupon_yield + cap_loss) / 100

    if use_brent:
        return _ytm_brent(price, coupon, nominal, n, frequency, tol)

    y_p = guess / frequency
    for _ in range(max_iter):
        if abs(y_p) < 1e-12:
            pv = nominal + coupon * n
        else:
            t = np.arange(1, n + 1)
            df = (1 + y_p) ** -t
            pv_coupons = np.sum(coupon * df)
            pv_face = nominal * (1 + y_p) ** -n
            pv = pv_coupons + pv_face
        f = pv - price
        if abs(y_p) < 1e-12:
            d_pv = -np.sum(coupon * t) - nominal * n
        else:
            d_pv = np.sum(-coupon * t * (1 + y_p) ** (-t - 1)) - nominal * n * (1 + y_p) ** (-n - 1)
        if abs(d_pv) < 1e-12:
            break
        y_new = y_p - f / d_pv
        if abs(y_new - y_p) < tol:
            return round(y_new * frequency * 100, 4)
        y_p = y_new

    result_nr = y_p * frequency * 100
    result_brent = _ytm_brent(price, coupon, nominal, n, frequency, tol)
    if result_brent is not None:
        return round(result_brent, 4)
    return round(result_nr, 4) if result_nr else None


def _ytm_brent(
    price: float,
    coupon: float,
    nominal: float,
    n: int,
    frequency: int,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> Optional[float]:
    if n <= 0:
        return None
    a, b = -0.95 / frequency + 1e-6, 5.0 / frequency
    fa = _pv_diff(a, price, coupon, nominal, n)
    fb = _pv_diff(b, price, coupon, nominal, n)
    if fa * fb > 0:
        return None
    for _ in range(max_iter):
        c = (a + b) / 2
        fc = _pv_diff(c, price, coupon, nominal, n)
        if abs(fc) < tol or (b - a) / 2 < tol:
            return c * frequency * 100
        if fa * fc < 0:
            b, fb = c, fc
        else:
            a, fa = c, fc
    return None


def _pv_diff(y: float, price: float, coupon: float, nominal: float, n: int) -> float:
    if abs(y) < 1e-12:
        pv = nominal + coupon * n
    else:
        t = np.arange(1, n + 1)
        pv = np.sum(coupon * (1 + y) ** -t) + nominal * (1 + y) ** -n
    return pv - price


def amortization_aware_duration(
    price_pct: float,
    coupon_rate: float,
    years_to_maturity: float,
    amort_schedule: list[tuple[float, float]] | None = None,
    nominal: float = 100.0,
    frequency: int = 2,
    ytm: Optional[float] = None,
) -> dict[str, float]:
    if amort_schedule is None:
        macaulay = _approx_macaulay(coupon_rate, ytm or 0, years_to_maturity, frequency, nominal)
        mod_dur = macaulay / (1 + (ytm or 0) / 100 / frequency) if ytm else 0
        return {
            "macaulayDuration": round(macaulay, 4),
            "modifiedDuration": round(mod_dur, 4),
            "amortizationAdjusted": False,
        }
    sorted_amort = sorted(amort_schedule, key=lambda x: x[0])
    y = (ytm or 0) / 100 / frequency
    remaining_nominal = nominal
    total_pv = 0.0
    weighted_time = 0.0
    for period_fraction, amort_pct in sorted_amort:
        amort_amount = remaining_nominal * amort_pct
        years_from_now = period_fraction * (1 / frequency)
        coupon_payment = (coupon_rate / 100) * remaining_nominal / frequency
        cash_flow = coupon_payment + (amort_amount if period_fraction == sorted_amort[-1][0] else 0)
        pv = cash_flow * (1 + y) ** (-(years_from_now * frequency)) if abs(y) > 1e-12 else cash_flow
        total_pv += pv
        weighted_time += years_from_now * pv
        remaining_nominal -= amort_amount
    macaulay = weighted_time / total_pv if total_pv > 0 else 0
    mod_dur = macaulay / (1 + y) if abs(y) > 1e-12 else macaulay
    return {
        "macaulayDuration": round(macaulay, 4),
        "modifiedDuration": round(mod_dur, 4),
        "amortizationAdjusted": True,
    }


def _approx_macaulay(
    coupon_rate: float,
    ytm: float,
    years_to_maturity: float,
    frequency: int,
    nominal: float = 100.0,
) -> float:
    n = int(years_to_maturity * frequency)
    if n <= 0:
        return 0.0
    rate = coupon_rate / 100
    c = rate * nominal / frequency
    y = ytm / 100 / frequency
    t = np.arange(1, n + 1)
    cf = np.full(n, c)
    if abs(y) < 1e-12:
        pv = cf.sum() + nominal
        weighted = np.sum(cf * t / frequency) + nominal * n / frequency
    else:
        df = (1 + y) ** -t
        pv = np.sum(cf * df) + nominal * (1 + y) ** -n
        weighted = np.sum(cf * df * t / frequency) + nominal * (1 + y) ** -n * n / frequency
    return weighted / pv if pv > 0 else 0


def price_from_ytm(
    ytm: float,
    coupon_rate: float,
    years_to_maturity: float,
    frequency: int,
    nominal: float = 100.0,
) -> float:
    if years_to_maturity <= 0 or frequency <= 0:
        return 0.0
    y = ytm / 100 / frequency
    rate = coupon_rate / 100
    n = int(years_to_maturity * frequency)
    if n <= 0:
        return 0.0
    coupon = rate * nominal / frequency
    pv = nominal if abs(y) < 1e-12 else coupon * (1 - (1 + y) ** -n) / y + nominal * (1 + y) ** -n
    return round(pv / nominal * 100, 4)
