# FinAdvisor

AI-финансовый ассистент для MOEX. Анализирует акции, ETF и облигации, строит сигналы и формирует портфель.

## Архитектура

```
finn-help/
├── src/                   # Python backend (FastAPI)
│   ├── analysis/          # Технический, фундаментальный, ML анализ
│   ├── collectors/        # MOEX ISS, CBR, новости (RSS)
│   ├── db/                # SQLAlchemy модели + SQLite
│   ├── geo/               # Геополитический риск
│   ├── interfaces/        # REST API + Telegram bot
│   ├── llm/               # Groq → Ollama → fallback
│   ├── notifications/     # Уведомления (Telegram)
│   ├── portfolio/         # Аллокатор портфеля
│   ├── scheduler/         # Ежедневный цикл обновления
│   └── signal/            # Fusion Engine (техно+фундамент+гео+ML)
├── web/                   # Next.js dashboard
└── tests/                 # pytest тесты
```

## Быстрый старт

```bash
# Клонировать
git clone https://github.com/xJleSx/finn-help.git
cd finn-help

# Настроить окружение
cp .env.example .env
# Отредактировать .env — указать GROQ_API_KEY

# Запустить через Docker
docker compose up --build -d

# Или локально (требуется Python 3.13+)
uv sync
uv run finn init
uv run finn update
uv run uvicorn src.interfaces.api.server:app
```

## CLI команды

| Команда | Описание |
|---------|----------|
| `finn init` | Инициализировать БД |
| `finn update` | Загрузить данные с MOEX (50 акций + 20 ETF + 10 облигаций) |
| `finn analyze TICKER` | Полный анализ инструмента |
| `finn list-instruments` | Список инструментов в БД |
| `finn rates` | Курсы валют ЦБ РФ |
| `finn auto` | Полный цикл: обновление + анализ + сигналы |
| `finn seed-portfolio` | Тестовый портфель (SBER, GAZP, LKOH) |

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Health check |
| GET | `/api/instruments` | Список инструментов |
| GET | `/api/instruments/{ticker}/signal` | Сигнал по инструменту |
| GET | `/api/instruments/{ticker}/advice` | Сигнал + LLM совет |
| POST | `/api/portfolio/allocate` | Аллокация портфеля |
| GET | `/api/news` | Новости |
| GET | `/api/geo-risk` | Геополитический риск |

## Переменные окружения

Ключевые переменные в `.env`:

| Переменная | Описание |
|------------|----------|
| `GROQ_API_KEY` | API ключ Groq (бесплатно на console.groq.com) |
| `DATABASE_URL` | Путь к БД (по умолч. sqlite:///data/finn.db) |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота |
| `TINKOFF_TOKEN` | Токен Tinkoff Invest API |
| `CORS_ORIGINS` | Разрешённые origins (через запятую) |

## Тестирование

```bash
uv sync --group dev
uv run pytest -v
```

## Лицензия

MIT
