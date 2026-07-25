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
    guess: float = 0.10,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> Optional[float]:
    if years_to_maturity <= 0 or price_pct <= 0:
        return None
    price = price_pct / 100 * nominal
    rate = coupon_rate / 100
    n = int(years_to_maturity * frequency)
    if n <= 0:
        return None
    coupon = rate * nominal / frequency
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
    return None


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
