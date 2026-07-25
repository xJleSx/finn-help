from __future__ import annotations

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from src.analysis.bonds_math import (
    clean_price_to_dirty,
    compute_accrued_interest,
    compute_convexity,
    compute_modified_duration,
    coupon_period_to_frequency,
    price_from_ytm,
    ytm_solver,
)


def test_ytm_solver_roundtrip():
    price = 95.5
    coupon = 8.5
    years = 3.5
    ytm = ytm_solver(price, coupon, years, nominal=100, frequency=2)
    assert ytm is not None
    assert 5 < ytm < 20
    restored = price_from_ytm(ytm, coupon, years, nominal=100, frequency=2)
    assert abs(restored - price) < 0.1


def test_ytm_solver_zero_coupon():
    ytm = ytm_solver(80, 0, 5, nominal=100, frequency=1)
    assert ytm is not None
    assert ytm > 0


def test_ytm_none_on_bad_input():
    assert ytm_solver(0, 5, 3) is None
    assert ytm_solver(100, 5, 0) is None


def test_modified_duration():
    mod = compute_modified_duration(4.5, 8.0, frequency=2)
    assert 4.0 < mod < 5.0


def test_modified_duration_zero():
    assert compute_modified_duration(0, 5, frequency=2) == 0.0


def test_convexity():
    cvx = compute_convexity(8.5, 9.5, 5.0, frequency=2, nominal=1000, price=98.0)
    assert cvx > 0


def test_convexity_zero_ytm():
    assert compute_convexity(5, 0, 5) == 0.0


def test_accrued_interest():
    ai = compute_accrued_interest(10.0, 1000.0, date(2026, 1, 1), settlement_date=date(2026, 4, 1), coupon_period_days=182)
    assert ai > 0


def test_accrued_interest_zero():
    assert compute_accrued_interest(0, 1000, date(2026, 1, 1)) == 0.0


def test_clean_to_dirty():
    dirty = clean_price_to_dirty(95.0, 1000.0, 25.0)
    assert dirty == 975.0


@given(
    st.floats(min_value=1, max_value=20),
    st.floats(min_value=1, max_value=15),
    st.floats(min_value=1, max_value=10),
)
@settings(max_examples=50)
def test_ytm_hypothesis(coupon, price_discount, years):
    price = max(50, 100 - price_discount)
    ytm = ytm_solver(price, coupon, years, nominal=100, frequency=2)
    if ytm is not None:
        assert 0 < ytm < 50


def test_coupon_period_to_frequency():
    assert coupon_period_to_frequency(None) == 2
    assert coupon_period_to_frequency(0) == 2
    assert coupon_period_to_frequency(-1) == 2
    assert coupon_period_to_frequency(30) == 12
    assert coupon_period_to_frequency(90) == 4
    assert coupon_period_to_frequency(182) == 2
    assert coupon_period_to_frequency(365) == 1


def test_accrued_interest_with_next_coupon():
    ai = compute_accrued_interest(
        10.0, 1000.0, date(2026, 1, 1),
        settlement_date=date(2026, 4, 1),
        coupon_period_days=182,
        next_coupon_date=date(2026, 7, 2),
    )
    assert ai > 0


def test_accrued_interest_before_coupon():
    assert compute_accrued_interest(10.0, 1000.0, date(2026, 6, 1), settlement_date=date(2026, 4, 1)) == 0.0


def test_accrued_interest_negative_rate():
    assert compute_accrued_interest(-5.0, 1000.0, date(2026, 1, 1)) == 0.0


def test_price_from_ytm_zero_years():
    assert price_from_ytm(10.0, 5.0, 0, frequency=2, nominal=100) == 0.0


def test_price_from_ytm_at_par():
    price = price_from_ytm(8.0, 8.0, 5.0, frequency=2, nominal=100)
    assert price == 100.0


def test_price_from_ytm_different_frequencies():
    p1 = price_from_ytm(8.0, 8.0, 5.0, frequency=1, nominal=100)
    p2 = price_from_ytm(8.0, 8.0, 5.0, frequency=4, nominal=100)
    assert abs(p1 - 100.0) < 0.5
    assert abs(p2 - 100.0) < 0.5


def test_convexity_without_price():
    cvx = compute_convexity(8.5, 9.5, 5.0, frequency=2, nominal=1000, price=None)
    assert cvx > 0


def test_convexity_short_maturity():
    assert compute_convexity(8.5, 9.5, 0.1, frequency=2) == 0.0
