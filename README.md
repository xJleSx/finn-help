# FinAdvisor

AI-финансовый ассистент для MOEX. Анализирует акции, ETF и облигации, строит сигналы, формирует портфель и управляет рисками.

## Возможности

- **Анализ**: технический (RSI, MACD, BB, SMA), фундаментальный (мультипликаторы, долг, дивиденды), ML (XGBoost, LightGBM, CatBoost + stacking), мультивременной, сентимент, геополитический риск
- **Сигналы**: Fusion Engine с динамическими весами под профиль пользователя
- **Портфель**: аллокатор с учётом риск-профиля (консервативный/умеренный/агрессивный)
- **Бэктестинг**: Monte-Carlo (500×252d), slippage, commission, regime detection
- **Дашборд**: Next.js, PortfolioSimulator, графики, сектора, макро-панель
- **Auth**: JWT, регистрация/логин, per-user портфель
- **Уведомления**: Telegram (сигналы, гео-риск, дивиденды, daily summary)
- **ML Ensemble**: lazy loading XGBoost/LightGBM/CatBoost, stacking meta-learner, uncertainty quantification

## Архитектура

```
finn-help/
├── src/                          # Python backend (FastAPI)
│   ├── analysis/
│   │   ├── ml/                   # XGBoost, LightGBM, CatBoost, Ensemble, Prophet
│   │   ├── backtest.py           # Monte-Carlo backtesting engine
│   │   ├── feature_store.py      # Feature cache (memory + DB)
│   │   ├── fundamental.py        # Мультипликаторы, аномалии
│   │   ├── technical.py          # RSI, MACD, BB, SMA, ATR
│   │   ├── sector.py             # Сектора: performance, correlation, volatility
│   │   └── service.py            # AnalysisService — оркестратор
│   ├── collectors/               # MOEX ISS, CBR, новости (RSS)
│   ├── db/                       # SQLAlchemy модели + SQLite + Alembic
│   ├── interfaces/api/           # REST API + auth (JWT, bcrypt)
│   ├── notifications/            # Сигналы, алерты (price target, divergence, rebalance)
│   ├── portfolio/                # Аллокатор портфеля
│   ├── scheduler/                # Ежедневный цикл
│   ├── signal/                   # Fusion Engine
│   ├── cache.py                  # Redis-кэш с in-memory fallback
│   └── user_profile.py           # Risk profiles + персонализация
├── web/                          # Next.js dashboard
│   ├── src/app/page.tsx          # PortfolioSimulator, MacroPanel, SectorHeatmap, Auth
│   └── Dockerfile
├── tests/                        # 189 pytest тестов
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
| GET | `/api/instruments/{ticker}/advice` | Сигнал + LLM совет |

### Портфель

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/portfolio` | Позиции (по пользователю) |
| POST | `/api/portfolio/add` | Добавить позицию |
| POST | `/api/portfolio/allocate` | Аллокация (`?capital=50000`) |

### Макро и Сектора

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/macro` | Brent, USD/RUB, IMOEX, ставка, CPI, M2 |
| GET | `/api/sectors/performance` | Доходность секторов (`?days=30`) |
| GET | `/api/sectors/correlation` | Корреляция секторов (`?days=90`) |
| GET | `/api/sectors/volatility` | Волатильность секторов (`?days=30`) |

### Алерты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/alerts/price-targets` | Ценовые цели (take-profit / stop-loss) |
| GET | `/api/alerts/divergence/{ticker}` | MACD/RSI дивергенции |
| GET | `/api/alerts/rebalance` | Rebalance алерты |

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
# 189 тестов (2026-06-15)
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
