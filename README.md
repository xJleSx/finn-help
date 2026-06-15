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
| `finn update` | Загрузить данные с MOEX (300 акций + 50 ETF + 50 облигаций) |
| `finn analyze TICKER` | Полный анализ инструмента |
| `finn list-instruments` | Список инструментов в БД |
| `finn rates` | Курсы валют ЦБ РФ |
| `finn auto` | Полный цикл: обновление + анализ + сигналы |
| `finn seed-portfolio` | Тестовый портфель (SBER, GAZP, LKOH) |

## Примеры ответов API

### Сигнал по инструменту

```json
GET /api/instruments/SBER/signal

{
  "ticker": "SBER",
  "action": "BUY",
  "confidence": 0.78,
  "weighted_score": 3.2,
  "max_portfolio_pct": 15,
  "reasons": [
    "RSI=42 — зона перепроданности",
    "MACD гистограмма положительная",
    "Цена выше SMA(50)"
  ],
  "components": {
    "technical": {"score": 1.5, "action": "BUY"},
    "fundamental": {"score": 0.8, "action": "BUY"},
    "ml": {"action": "BUY", "confidence": 0.65},
    "prophet": {"target_price": 325.0, "confidence": 0.72},
    "sentiment": {"score": 0.3, "divergence": 0.1}
  },
  "risk": {
    "volatility_regime": "LOW",
    "var_95": 2.3,
    "stop_loss": 265.0
  }
}
```

### Сигнал + LLM совет

```json
GET /api/instruments/SBER/advice

{
  "signal": { "...": "..." },
  "advice": "Сбер — сильный buy. RSI в зоне перепроданности, MACD дал сигнал на покупку.
  Целевая цена по Prophet — 325₽ (+13% от текущей).
  Рекомендуемая доля — до 15% портфеля.
  Стоп-лосс: 265₽."
}
```

### Список инструментов

```json
GET /api/instruments?type=stock

[
  {
    "id": 1,
    "ticker": "SBER",
    "full_name": "Сбер Банк",
    "sector": "finance",
    "type": "stock",
    "last_price": 287.50,
    "last_date": "2025-06-13"
  }
]
```

### Аллокация портфеля

```json
POST /api/portfolio/allocate
Body: {"capital": 100000}

{
  "positions": [
    {"ticker": "SBER", "weight": 0.25, "amount": 25000, "shares": 87},
    {"ticker": "LKOH", "weight": 0.20, "amount": 20000, "shares": 3}
  ],
  "total": 100000,
  "remaining": 0
}
```

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
