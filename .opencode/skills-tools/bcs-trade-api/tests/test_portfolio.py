"""Regression tests for the BCS /portfolio quirks.

The single most important test in this file: BCS lists every position
once per settlement term (T0, T1, T2, T365). Summing all of them
over-counts by 4×. These tests pin the filter and dedupe logic so we
don't reintroduce the bug.
"""
from __future__ import annotations

import json
from pathlib import Path

from bcs_trade.cache import _extract_total
from bcs_trade.portfolio import dedupe_positions, filter_by_term

FIXTURE = Path(__file__).parent / "fixtures" / "portfolio_sample.json"


def _raw() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["positions"]


def test_filter_by_term_keeps_only_t0() -> None:
    raw = _raw()
    t0 = filter_by_term(raw, term="T0")
    assert len(t0) == 3  # SBER/TQBR, SBER/SPBXM, GAZP
    assert all(r["term"] == "T0" for r in t0)


def test_filter_by_term_t365_returns_planned_settlements() -> None:
    raw = _raw()
    t365 = filter_by_term(raw, term="T365")
    assert len(t365) == 2  # SBER/TQBR, GAZP
    assert all(r["term"] == "T365" for r in t365)


def test_dedupe_drops_duplicate_class_under_same_term() -> None:
    raw = _raw()
    t0 = filter_by_term(raw, term="T0")
    unique = dedupe_positions(t0)
    # SBER appears under TQBR and SPBXM — both are kept (different boards).
    assert len(unique) == 3
    codes = {r["classCode"] for r in unique if r["ticker"] == "SBER"}
    assert codes == {"TQBR", "SPBXM"}


def test_dedupe_is_noop_when_no_duplicates() -> None:
    raw = _raw()
    t0 = filter_by_term(raw, term="T0")
    assert dedupe_positions(t0) == t0


def test_total_after_filter_and_dedupe_is_not_quadrupled() -> None:
    """The bug: BCS returns each holding once per settlement term
    (T0, T1, T2, T365). Naive summation of the raw 9-record fixture
    gives 1250. The correct T0 view is 350.

    This test guards against the 4× over-counting coming back.
    """
    raw = _raw()
    naive = _extract_total(raw)
    t0_unique = dedupe_positions(filter_by_term(raw, term="T0"))
    correct = _extract_total(t0_unique)

    assert naive == 1250.0
    assert correct == 350.0
    # Documents the over-count ratio for any reader who hits this
    # test failure in the future.
    assert naive / correct == 1250.0 / 350.0
