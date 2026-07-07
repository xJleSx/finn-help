# ADR-004: Collector Unification

**Status:** Accepted
**Date:** 2026-07-06

## Context
12 data collectors existed with different HTTP patterns: some used BaseCollector with circuit-breaker/retry, others used raw httpx/aiohttp/urllib with ad-hoc error handling.

## Decision
All collectors now extend `BaseCollector` which provides:
- `httpx.AsyncClient` with configurable timeout
- Tenacity-based retry (exponential backoff, 3 attempts)
- Circuit breaker pattern (via `src/core/resilience.py`)
- `_fetch_json()`, `_fetch_text()`, `_fetch_json_or_list()` methods

## Consequences
- Consistent error handling across all data sources
- Standardized retry and circuit-breaking
- Each collector inherits monitoring capabilities
