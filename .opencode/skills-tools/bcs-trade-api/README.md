# BCS Trade API — opencode skill

Портабельный CLI-скилл для работы с публичным API
[БКС Мир инвестиций](https://trade-api.bcs.ru/).

## Возможности

- Авторизация по refresh-токену (Keycloak OIDC через `be.broker.ru`);
- Просмотр портфеля (`/portfolio`) и лимитов/кэша (`/limits`);
- Котировки и справочник инструментов (`/market-data`, `/information`);
- Заявки: создать / отредактировать / отменить (`/operations`);
- Сделки (`/trades`);
- Локальный SQLite для снапшотов портфеля (stateful-плацдарм, не кеш).

## Установка

```bash
cd bcs-trade-api
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # вписать BCS_REFRESH_TOKEN
```

## Первый запуск

```bash
bcs auth status              # проверить токен
bcs portfolio --format human # текущий портфель
bcs limits --format json     # кэш и лимиты
```

## Конфигурация (`.env`)

| Переменная | Описание |
|---|---|
| `BCS_REFRESH_TOKEN` | Refresh-токен (обязательно, 90 дней) |
| `BCS_ACCOUNT` | ID счёта по умолчанию для заявок |
| `BCS_READ_ONLY=1` | Запретить мутирующие команды |
| `BCS_SANDBOX=1` | Переключиться на песочницу |
| `BCS_LOG_LEVEL` | `DEBUG` / `INFO` / `WARN` / `ERROR` |

## Структура

```
bcs.py            CLI (argparse + subcommands)
bcs               unix-обёртка
bcs_trade/        пакет с логикой
  auth.py         refresh → access token
  portfolio.py    /portfolio, /limits, dedupe, filter_by_term
  market.py       /market-data, /information
  orders.py       /operations
  trades.py       /trades
  db.py           SQLite-схема, миграции
  cache.py        работа с .bcs-cache/
  config.py       .env, пути
  endpoints.py    URL-карта BCS API
  http_client.py  сессия, retry, auth-header
  models.py       dataclasses для ответов API
  formatters.py   JSON / human вывод
  errors.py       исключения
tests/            юнит-тесты
```

## Ключевые особенности

### Settlement lag

Кэш (`moneyLimits`) обновляется сразу после сделки, но количества
позиций — после клиринга (T+1/T+2). Не паникуйте, если позиции
«не изменились» сразу после покупки/продажи.

### `/portfolio` дублирует по term

API возвращает одну позицию по 4 term'ам (T0, T1, T2, T365).
CLI фильтрует по T0 по умолчанию и дедуплицирует по
`(ticker, classCode, instrumentType)`. Используйте `--term T365`
только для отладки расчётов расчётов.

### Кэш не в `portfolio`

Для просмотра доступного кэша используйте `bcs limits`, а не
`bcs portfolio`. Portfolio показывает только позиции.
