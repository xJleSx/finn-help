---
name: finn-help
description: >
  Use for ALL work on the finn-help / FinAdvisor project.
  Covers Python/FastAPI backend, TypeScript/Next.js frontend, SQL/PostgreSQL,
  pytest testing, security, API design, architecture, ML/trading domain,
  MOEX market specifics, and code review. Use ONLY for this project.
---

# finn-help / FinAdvisor — Unified Project Skill

AI-powered financial assistant for MOEX markets.

## Project structure

```
src/                   # Python backend (FastAPI)
  analysis/            #   Technical, fundamental, ML ensemble, backtesting
  analysis/ml/         #   XGBoost, LightGBM, CatBoost, Prophet, stacking
  signals/             #   Signal Fusion Engine (BUY/SELL/HOLD)
  trading/             #   T-Bank gRPC, execution engine, risk guards
  collectors/          #   MOEX ISS, CBR, SmartLab, news RSS
  interfaces/api/      #   FastAPI routes, auth, rate limiter
  portfolio/           #   Portfolio allocation, risk
  llm/                 #   LLM router (Groq → Ollama fallback)
  db/                  #   SQLAlchemy 2.0 models, Alembic migrations
  core/                #   Logging, health, circuit breakers, Sentry
  scheduler/           #   Background daily cycles
  cli.py               #   Typer CLI (finn analyze, backtest, auto)
web/                   # Next.js 16 + React 19 + Tailwind v4 frontend
tests/                 # 1200+ pytest tests
alembic/               # Database migrations
```

## Python backend conventions

- **Python 3.13+**, strict mypy (`--strict`), ruff (line-length 120, select E/F/I/N/W)
- **FastAPI** async endpoints with Pydantic v2 schemas, dependency injection
- **SQLAlchemy 2.0** async ORM (`AsyncSession`); sync fallback for CLI
- **Alembic** migrations; run `alembic upgrade head` before testing
- **pytest 9.1+** with `pytest-asyncio` (auto mode), `pytest-httpx` for mocks
- **uv** for dependencies: `uv sync`, `uv run pytest`, `uv run mypy src/`
- Use `@cached` decorator for Redis caching (in-memory dict fallback)
- Circuit breakers via `src/core/resilience.py` for all external calls
- Structured logging via `structlog`; Sentry for errors; Prometheus at `/metrics`

### Async patterns

- All DB sessions use `async with async_session() as session` (FastAPI dependency)
- All HTTP calls use `httpx.AsyncClient` with circuit breakers
- Background tasks via asyncio or the scheduler module

### API patterns

- RESTful FastAPI with JWT auth (HS256 + bcrypt), OAuth2 password flow
- Rate limiting via `slowapi`; SSE streaming at `/api/events`
- Health check at `/api/health` (DB, ML models, scheduler, circuit breakers)
- Route prefix `/api/`; version via URL, not headers

## TypeScript frontend conventions

- **Next.js 16** App Router, **React 19**, **TypeScript 5**
- **Tailwind CSS v4** with PostCSS
- `lightweight-charts` for trading charts
- API client in `web/src/lib/api.ts` (REST + SSE)
- Run: `npm run dev`, `npm run build`

## Database conventions

- **PostgreSQL 16** (prod, asyncpg) / **SQLite** (dev, aiosqlite)
- Dual DB via `DATABASE_URL` env var
- 20+ models in `src/db/models.py` (Instrument, Price, Signal, Prediction, Portfolio, User, News, etc.)
- Alembic for migrations; `batch` mode for SQLite compatibility
- Watch for N+1: use `selectinload` / `joinedload` in async paths
- Composite indexes on `(ticker, timestamp)`, `(user_id, portfolio_id)`

## Testing conventions

- pytest with pytest-asyncio, pytest-httpx, pytest-cov
- Fixtures in `tests/conftest.py`: in-memory SQLite (sync/async), mock clients
- Coverage threshold: `fail_under = 60`
- Run: `uv run pytest -v` or `uv run pytest tests/ --cov=src -q`

## ML model conventions

- **Stacking ensemble**: XGBoost + LightGBM + CatBoost base → meta-learner
- **Walk-forward validation** for time-series correctness
- **Model registry**: `src/model_registry.py` (cloudpickle-based)
- **Lazy loading**: models loaded on first inference
- **Feature alignment**: must match training pipeline exactly

## Trading domain

- **T-Bank Invest API** via gRPC in `src/trading/brokers/tbank.py`
- **Dry-run mode** by default; `ENABLE_TRADING=true` to activate
- **Signal Fusion Engine** (`src/signals/engine.py`): combines technical, fundamental, ML, sentiment, geopolitical, multi-timeframe → BUY/SELL/HOLD/CAUTIOUS_BUY with confidence
- **Risk guards**: max trades/day, kill switch, stop-loss, audit logging
- Circuit breakers on broker connection

## MOEX market specifics

- Moscow Exchange data via MOEX ISS API (REST, free)
- Central Bank of Russia (CBR) for macro data
- Ticker format: `SBER`, `GAZP`, `LKOH`, `YDEX` (no exchange prefix in local context)
- Market data includes: equities, bonds (OFZ, corporate), ETFs, derivatives
- Settlement: T+1 for equities

## Output rules — экономия токенов

- **НИКОГДА** не выводи код в текстовых ответах. Ни строки. Ни diff. Ничего.
- Инструменты `edit`/`write`/`bash` уже показывают результат в TUI — не дублируй его текстом.
- В ответе пиши только 1-3 предложения: что сделано и в каком файле. Без листингов кода.
- Всегда используй `edit` вместо `write` для изменений — `edit` показывает только diff, а `write` выводит весь файл.

## Code review rules

- All functions must have type annotations (no `Any` unless unavoidable)
- No bare `except:`; use specific exception types
- All DB operations must use async sessions in API paths
- New logic requires pytest tests
- Check for: N+1 queries, cache misses, missing circuit breakers, unawaited coroutines

## External tools (installed in project)

- **financemarker-api**: Russian market fundamentals, dividends, ratios, analyst ideas. CLI: `fmc stock MOEX:*
  `, `fmc dividends`, `fmc ratios`. API key: `FM_API_TOKEN` in `.env`
- **claude-trading-skills (ML section)**: signal classification, feature engineering for XGBoost/LightGBM. Complements the existing ML ensemble.

## CLI commands

- `finn init` — setup DB, seed data
- `finn analyze TICKER` — full analysis pipeline
- `finn backtest TICKER` — backtest with Monte Carlo
- `finn auto` — full daily cycle
- `uv run pytest` — run tests
- `uv run mypy src/` — type check
- `uv run ruff check src/` — lint

## Infrastructure

- **Docker**: `docker compose up` starts PostgreSQL + API + web
- **Entrypoint**: waits for PG, runs Alembic migrations, starts Uvicorn
- **CI**: GitHub Actions (lint → typecheck → test → security)
- **Logging**: structlog (`LOG_LEVEL=INFO`), Sentry for errors
- **Monitoring**: Prometheus metrics at `/metrics`, health at `/api/health`
