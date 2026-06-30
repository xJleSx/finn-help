# FinAdvisor

AI-финансовый ассистент для MOEX. Анализирует акции, ETF и облигации, строит сигналы, формирует портфель и управляет рисками.

## Возможности

- **Анализ**: технический (RSI, MACD, BB, SMA, ATR), фундаментальный (P/E, ROE, IFRS отчёты, мультипликаторы), ML (XGBoost + stacking), мультивременной, сентимент (LLM), геополитический риск, секторный риск
- **Enrichment**: профили компаний, корпоративные события (дивиденды, байбэки, сплиты), параметры облигаций (YTM, рейтинг, оферта, амортизация), альтернативные данные (CBR, Росстат, Google Trends)
- **Сигналы**: Fusion Engine с динамическими весами под профиль пользователя
- **Портфель**: аллокатор с учётом риск-профиля и фундаментальных метрик (P/E, ROE, D/E), ребалансировка
- **Уведомления**: Telegram (сигналы, дивиденды, daily summary, enrichment-алерты)
- **Торговля**: исполнение заявок через T-Bank Invest API (gRPC), стоп-лоссы, аудит, kill switch
- **Алерты**: приближение погашения облигаций, аномалии в отчётности, падение уверенности сигнала, корпоративные события
- **Бэктестинг**: Monte-Carlo (500x252d), slippage, commission, regime detection
- **API**: FastAPI + JWT, SSE stream, health check с метриками покрытия
- **LLM**: Groq (primary) / Ollama (fallback), WolframAlpha enrichment, контекст компании/фин.отчётности
- **ML Ensemble**: lazy loading XGBoost/LightGBM/CatBoost, stacking meta-learner, uncertainty quantification

## Архитектура

```
finn-help/
├── src/                          # Python backend (FastAPI)
│   ├── analysis/
│   │   ├── ml/                   # XGBoost, LightGBM, CatBoost, Ensemble, Prophet, SentimentEvolution
│   │   ├── inference/            # Granger causality, causal impact, instrument graph
│   │   ├── backtest.py           # Monte-Carlo backtesting engine
│   │   ├── fundamental.py        # Мультипликаторы, аномалии, сравнение с сектором
│   │   ├── technical.py          # RSI, MACD, BB, SMA, ATR
│   │   ├── sector.py             # Сектора: performance, correlation, volatility
│   │   ├── rebalancing.py        # Ребалансировка портфеля
│   │   ├── risk_explorer.py      # VaR/CVaR, deep-dive, концентрация
│   │   ├── summarizer.py         # Кластеризация новостей + LLM дайджест
│   │   └── service.py            # AnalysisService — оркестратор
│   ├── collectors/               # MOEX ISS, CBR, SmartLab, новости (RSS), Telegram
│   ├── data/                     # Sector impact engine, geopolitical risk, dashboard provider
│   ├── db/                       # SQLAlchemy модели + PostgreSQL + Alembic
│   ├── alerts/                   # Alert engine, генераторы, дедупликация
│   ├── interfaces/
│   │   ├── api/                  # REST API + auth (JWT, bcrypt)
│   │   ├── telegram.py           # Telegram bot (python-telegram-bot v20)
│   │   ├── telegram_alerter.py   # Форматирование и отправка алертов
│   │   ├── nlq.py                # Natural Language Query engine
│   │   ├── response_formatter.py # Сборка enrichment-блоков для ответов
│   ├── social/                   # Социальный сентимент (LLM), агрегация, признаки
│   ├── llm/                      # Groq + Ollama роутер, WolframAlpha, промпты
│   ├── notifications/            # Сигналы, алерты (price target, divergence, rebalance)
│   ├── portfolio/                # Аллокатор портфеля (с фундаментальными метриками)
│   ├── scheduler/                # Ежедневный/еженедельный цикл
│   ├── signal/                   # Fusion Engine
│   ├── trading/                  # Исполнение сделок, риск-менеджмент, стоп-лоссы, аудит
│   │   ├── brokers/tbank.py      # T-Bank Invest gRPC клиент
│   │   ├── execution/            # Engine, stoploss, loop, audit
│   │   └── risk/                 # Guards, manager, kill switch
│   ├── geo/                      # Геополитический риск, divergence
│   ├── cache.py                  # Redis-кэш с in-memory fallback
│   └── user_profile.py           # Risk profiles + персонализация
├── web/                          # Next.js dashboard
├── tests/                        # 1207 pytest тестов
├── tools/                        # audit_formatters.py
└── Dockerfile / docker-compose.yml
```

## Быстрый старт

```bash
# Клонировать
git clone https://github.com/xJleSx/finn-help.git
cd finn-help

# Настроить окружение
cp .env.example .env
# Отредактировать .env — указать GROQ_API_KEY
# ⚠️ .env содержит реальные токены. На production: icacls .env /inheritance:r /grant "%USERNAME%:F" (Windows) или chmod 600 .env (Linux/macOS)

# Запустить через Docker
docker compose up --build -d

# Или локально (Python 3.13+)
uv sync
uv run finn init
uv run finn update
uv run uvicorn src.interfaces.api.server:app --reload

# Фронтенд (отдельный терминал)
cd web
npm install
npm run dev
```

Откройте http://localhost:3000

## CLI команды

| Команда | Описание |
|---------|----------|
| `finn init` | Инициализировать БД + миграции |
| `finn update` | Загрузить данные с MOEX (300 акций + 50 ETF + 50 облигаций) |
| `finn analyze TICKER` | Полный анализ инструмента |
| `finn list-instruments` | Список инструментов в БД |
| `finn rates` | Курсы валют ЦБ РФ |
| `finn auto` | Полный цикл: обновление → анализ → сигналы |
| `finn seed-portfolio` | Тестовый портфель |

## API Endpoints

### Auth

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/auth/register` | Регистрация (username, password, risk_profile) |
| POST | `/api/auth/login` | Логин, получает JWT |
| GET | `/api/auth/me` | Текущий пользователь (требует токен) |

### Инструменты и анализ

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Health check |
| GET | `/api/instruments` | Список инструментов (`?type=stock/bond/etf`) |
| GET | `/api/instruments/{ticker}` | Детали инструмента |
| GET | `/api/instruments/{ticker}/prices` | Цены (`?days=365`) |
| GET | `/api/instruments/{ticker}/indicators` | Технические индикаторы |
| GET | `/api/instruments/{ticker}/signal` | Сигнал (RSI, MACD, фундамент, ML, гео) |
| GET | `/api/instruments/{ticker}/trade-plan` | Торговый план (вход/цели/стоп) |
| GET | `/api/instruments/{ticker}/advice` | Сигнал + LLM совет |
| POST | `/api/ask` | Вопрос LLM с контекстом |

### Портфель

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/portfolio` | Позиции (по пользователю) |
| POST | `/api/portfolio/add` | Добавить позицию |
| POST | `/api/portfolio/allocate` | Аллокация с учётом фундаментала (`?capital=50000`) |

### Макро и Сектора

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/macro` | Brent, USD/RUB, IMOEX, ставка, CPI, M2 |
| GET | `/api/sectors/performance` | Доходность секторов (`?days=30`) |
| GET | `/api/sectors/correlation` | Корреляция секторов (`?days=90`) |
| GET | `/api/sectors/volatility` | Волатильность секторов (`?days=30`) |

### Алерты и Риски

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/alerts` | Алерты пользователя |
| POST | `/api/alerts/refresh` | Пересчитать алерты |
| GET | `/api/alerts/price-targets` | Ценовые цели (take-profit / stop-loss) |
| GET | `/api/alerts/divergence/{ticker}` | MACD/RSI дивергенции |
| GET | `/api/alerts/rebalance` | Rebalance алерты |
| GET | `/api/risk/portfolio` | Риск-метрики портфеля (VaR, CVaR, концентрация) |
| GET | `/api/risk/deep-dive/{ticker}` | Deep-dive по инструменту |

### Анализ

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/analysis/scenario` | Стресс-тест портфеля |
| GET | `/api/analysis/causal/{ticker}` | Причинно-следственный анализ (Granger) |

### Прочее

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/news` | Новости (`?limit=20`) |
| GET | `/api/geo-risk` | Геополитический риск (`?days=30`) |
| GET | `/api/events` | SSE stream (инструменты, сигналы) |

## Risk Profiles

| Профиль | Техно | Фундам | Гео | ML | Сентимент | MTF | Макс. позиция |
|---------|-------|--------|-----|-----|-----------|-----|------|
| Консервативный | 30% | 25% | 20% | 8% | 7% | 10% | 10% |
| Умеренный | 35% | 18% | 17% | 13% | 12% | 5% | 20% |
| Агрессивный | 40% | 10% | 10% | 20% | 15% | 5% | 35% |

## Тестирование

```bash
uv sync --group dev
uv run pytest -v
# 1207 тестов (2026-06-29)
```

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `GROQ_API_KEY` | API ключ Groq (бесплатно на console.groq.com) |
| `DATABASE_URL` | Путь к БД (по умолч. sqlite:///data/finn.db) |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота |
| `TINKOFF_TOKEN` | Токен Tinkoff Invest API |
| `CORS_ORIGINS` | Разрешённые origins (через запятую) |

## Технологии

- **Backend**: Python 3.13, FastAPI, SQLAlchemy, SQLite, XGBoost, LightGBM, CatBoost
- **Frontend**: Next.js 16, React 19, Tailwind CSS, lightweight-charts
- **Auth**: JWT (python-jose), bcrypt
- **ML**: Stacking ensemble, walk-forward validation, Prophet
- **Deploy**: Docker multi-stage build, docker-compose, healthcheck

## Лицензия

MIT
