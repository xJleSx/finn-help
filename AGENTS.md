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

## Master Plan: 6 Phases

### Phase 0 — Чистка и базовая настройка (DONE)
- .gitignore (Python, IDE, OS)
- Мёртвый код: удалить неиспользуемые файлы, импорты, переменные
- 6 падающих тестов — починить
- mypy strict 847→0
- CI base: ruff, security, coverage, Postgres service
- config: .env.example, pyproject.toml
- Пустые __init__.py удалены
- Мусор из git-трекинга убран

### Phase 1 — Архитектура и рефакторинг (PARTIAL)
**Done:**
- Pydantic response-модели: schemas.py + response_model= на всех JSON-роутах
- allocator.allocate_async → native async (убран run_in_executor)
- item_risk_async в risk.py (используется allocator)

**Todo / Blocked:**
- service.py: sync/async рефакторинг (~1081 строка, 10 sync/async пар, ~5 внешних вызывающих). Sync-методы нужны CLI/telegram/llm/scheduler. Отложен — требует отдельного планирования.
- Gateway/Repository слой: выделить из service.py和数据-access в отдельный слой
- Enum для type safety: instrument types, signal types, roles, risk profiles
- Устранить дубликаты _analyze_core, _compute_ml, _build_trade_plan (sync и async версии)

### Phase 2 — ML и модели (IN PROGRESS)
**Исследование завершено. Ключевые проблемы:**
- ~250 строк дубликатов в каждом из 3 классификаторов (XGBoost/LightGBM/CatBoost) — ~80% идентичного кода
- price_targets.py — нулевое тестовое покрытие (entry zone, stop-loss, take-profit)
- Гиперпараметры хардкодом (n_estimators=50, max_depth=3, lr=0.1) в каждом классе
- ensemble.predict() вызывает walk-forward validate на каждый запрос (9 рефитов!)
- Позиционный доступ results[0]/[1]/[2] ломается если catboost не импортирован
- Тесты отсутствуют: train(), save(), load(), score(), fit(), anomaly_mask

**План:**
1. BaseMLClassifier — выделить общий базовый класс, убрать дубликаты
2. Гиперпараметры вынести в src/config
3. ensemble.py: кеш OOS, починить позиционный доступ
4. price_targets.py: тесты для всей торговой логики
5. Тесты train/save/load/score/fit + anomaly_mask для всех классификаторов
6. model_registry.py: async, убрать хардкод пути data/models/

### Phase 3 — Безопасность
- JWT: улучшить (refresh token, expiration, blacklist)
- Input validation: Pydantic на всех входах
- Secrets management: убрать хардкод ключей, vault/env
- Rate limiting: review и донастройка
- SQL injection: parameterized queries (проверить)
- CORS: review настроек

### Phase 4 — Тестирование и CI
- Интеграционные тесты: БД, API end-to-end
- Coverage: поднять с 40% до целевого уровня
- CI pipeline: parallel jobs, cache, artifacts
- Property-based testing (hypothesis) для core-логики
- Load/stress тесты для API

### Phase 5 — Документация и мониторинг
- API docs: OpenAPI улучшения, примеры
- Logging: структурированный (JSON), уровни, ротация
- Метрики: Prometheus + Grafana
- Health checks: расширить /api/health
- Monitoring: алерты, дашборды

---

## Продвинутые улучшения (после базовых 8 фаз)

### 1. Предиктивная аналитика и ML
- News Impact Prediction Model: DONE (XGBoost Regressor, 3 horizons, 24 features)
- Sentiment Evolution Prediction: PENDING
- Anomaly Detection: DONE (Volume/Sentiment Isolation Forest + Source/Topic frequency analysis + PyTorch Autoencoder, unified detector)
- Causal Inference: PENDING
- News Impact Attribution: DONE (SHAP-based feature importance per news article)

### 2. Расширение источников данных
- Social Media: DONE (Telegram collector with keyword ticker detection + sentiment)
- Alternative Data: DONE (CBR rates via XML API + stub framework for Minfin/Rosstat)
- Official Sources: DONE (CBR XML parser + MacroIndicator model)
- Earnings Calls: PENDING

### 3. Автоматизация и оптимизация
- Automated Summarization: DONE (LLM news cluster summarizer with fallback)
- Intelligent Alert System: DONE
- Automated Portfolio Rebalancing: PENDING
- Self-Learning System: DONE (feedback loop, auto-retrain, A/B model comparison)

### 4. Продвинутая аналитика и визуализация
- News Impact Attribution (Shapley values): DONE
- Scenario Analysis & Stress Testing: DONE
- Interactive Risk Explorer: PENDING
- Natural Language Query Interface: PENDING

### 5. Интеграции и экосистема
- Broker API Integration: DONE (Tinkoff broker client with sandbox/mock — market/limit orders, portfolio sync)
- Multi-Market Expansion: PENDING
- Public API: DONE (5 new endpoints: scenario, impact, alerts)
- Улучшенный Telegram Bot: DONE (AlertNotifier: alerts, digest, scenario results)

### Приоритетная дорожная карта
| Этап | Статус |
|------|--------|
| 1. News Impact Prediction + Anomaly Detection + Alerts | DONE |
| 2. Scenario Analysis + Social Media + Alternative Data | DONE |
| 3. Broker Integration + Self-Learning + Attribution | DONE |
