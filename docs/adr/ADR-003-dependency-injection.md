# ADR-003: Dependency Injection Container

**Status:** Accepted (Phase 1)
**Date:** 2026-07-06

## Context
Services were instantiated ad-hoc: some via FastAPI Depends, others as global module-level singletons, others inline at point of use. This made testing difficult and created hidden coupling.

## Decision
Introduce a lightweight DI container (`src/core/container.py`) with:
- `register()`, `get()`, `register_factory()` methods
- `wire()` function that registers all singleton services
- Phase 1: Wire API-layer services (AuthService, PortfolioService, MarketService, AnalysisService, etc.)
- Phase 2+: Migrate module-level singletons and inline instantiations

## Consequences
- Consistent service lifecycle management
- Easier testing via `container_for_testing()`
- Eliminates hidden coupling (MarketService no longer creates AnalysisService internally)
