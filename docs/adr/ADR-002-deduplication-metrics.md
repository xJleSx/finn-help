# ADR-002: Metrics and Query Deduplication

**Status:** Accepted
**Date:** 2026-07-06

## Context
Performance metrics (sharpe, sortino, max_drawdown) were duplicated across `analysis/backtest.py`, `analysis/personal_backtest.py`, `signals/engine.py`, and `trading/metrics.py`. Common DB queries were duplicated across multiple files.

## Decision
- Extract shared metrics into `analysis/metrics.py` (5 canonical functions)
- Extract shared DB queries into `db/queries.py` (4 helpers: get_instrument, get_instrument_by_id, get_latest_price, get_price_history)
- Centralize shared constants in `src/constants.py` (ACTION_EMOJI)

## Consequences
- Single source of truth for metrics calculations
- Reduced code duplication
- Easier to maintain and test
