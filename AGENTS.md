# FinAdvisor — AI Financial Advisor

## Project structure
- `src/` — Python backend (CLI + API)
- `web/` — Next.js dashboard
- `data/` — SQLite database

## Commands
- `uv run finn init` — init database
- `uv run finn update SBER` — fetch data for ticker
- `uv run finn analyze SBER` — full analysis (use --no-llm to skip LLM)
- `uv run finn list` — list instruments
- `uv run finn rates` — CBR exchange rates
- `uv run api` — start FastAPI (uvicorn src.interfaces.api.server:app)
- `uv run web` — start Next.js (cd web && npm run dev)

## Architecture
- MOEX ISS + CBR + RSS → Collector
- TA-Lib/pandas → Technical Analyzer
- Prophet/XGBoost → ML Predictor (future)
- Sentiment Divergence + GeoRisk Scorer → Geo module
- Groq → ollama → Fallback → LLM Router
- FastAPI → Next.js → Web Dashboard

## Environment
- `.env` — API keys (Groq, Tinkoff)
- Python 3.13+
- Node.js 22+

## Rules for AI assistant
- Commit messages: plain ASCII, no long dashes (--), no arrows (→, <-), no emoji
- No AI-generated comments, signatures, or markers in code
- No AI tags in commit messages or PR descriptions
- Keep code clean of tool-specific artifacts

---

## Master Plan: Обогащение БД и качество ответов бота

### Этап 0 — Наполнение и обогащение БД (NEW PRIORITY)
Цель: LLM получает богатый ticker_context (фин.отчётность, bond params, события).

**Collectors (collectors/moex.py + financials.py):**
- Полные профили компаний: описание, сектор, отрасль, employees, founded, website
- Финансовая отчётность МСФО/РСБУ (прибыль, выручка, ROE, долг, дивиденды)
- Параметры облигаций (купон, YTM, рейтинг, оферта, амортизация, дюрация)
- Корпоративные события (дивиденды, buyback, splits, доп.эмиссия)

**Модели (db/models.py):**
- CompanyProfile — полное описание компании
- FinancialReport — улучшить coverage
- BondOffering — улучшить (добавить рейтинг, оферту, амортизацию)
- CorporateEvent — buyback, splits, доп.эмиссия

**Регулярное обновление (scheduler/collectors.py):**
- Ежедневно: цены, новости, курсы валют
- Еженедельно: фундаментальные метрики, фин.отчётность
- Ежемесячно: профили компаний, облигации

**Миграции:** Alembic для всех новых моделей.

### Этап 1 — Анализ текущих ответов бота (~1ч)
- Собрать примеры ответов /top, /analyze, /allocate
- Оценить качество контекста из БД
- Выявить gaps в данных

### Этап 2 — Дизайн новых форматов ответов (2-3ч)
- Шаблоны с использованием обогащённых данных (фин. метрики, дивиденды, bond analysis)
- Персонализация под риск-профиль пользователя
- Компактные / расширенные режимы вывода

### Этап 3 — Рефакторинг форматирования и промптов (4-6ч)
- src/interfaces/formatters.py — унифицированные форматтеры
- Обновление LLM-промптов (src/llm/prompts.py)
- Интеграция богатого контекста из БД в LLM
- Rich-форматирование для терминала (CLI)

### Этап 4 — Тестирование + итерации (2-3ч)
- Тесты на реальных данных из БД
- Сравнение "до/после" на примерах
- A/B тестирование промптов

### Этап 5 — Расширение
- Графики в ответах (ASCII-art, Mermaid)
- Персональные отчёты PDF
- Advanced context для пользовательских вопросов

---

## Предыдущие этапы (завершены)

### Audit 12 шагов (DONE)
| Шаг | Статус |
|-----|--------|
| 1. News clustering (BERT) | DONE |
| 2. LLM spam filter | DONE |
| 3. Hierarchical categorization | DONE |
| 4. Sector Impact Engine v2 | DONE |
| 5. Company Risk Aggregator v2 | DONE |
| 6. Geopolitical Risk v2 | DONE |
| 7. News Impact + LSTM ensemble | DONE |
| 8. Alternative Data framework | DONE |
| 9. Rebalancing + Broker | DONE |
| 10. Causal Inference | DONE |
| 11. NL Query expansion | DONE |
| 12. Alert System enhancement | DONE |

### Прочее
- LICENSE: MIT → BUSL 1.1 (change date 4 years, Apache 2.0 fallback)
- CI: 1132 tests passing, ruff clean
- Phase 1 (Architecture): Pydantic models, async allocator, risk refactor
- Phase 2 (ML): XGBoost/LightGBM/CatBoost ensemble, anomaly detection, price targets
- Phase 3 (Security): JWT, bcrypt, rate limiting, CORS
- Phase 4 (Testing): 1132 tests, coverage ~47%
- Phase 5 (Docs): OpenAPI, logging, health checks
