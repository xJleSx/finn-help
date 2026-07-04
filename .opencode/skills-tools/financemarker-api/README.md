# FinanceMarker API — opencode skill

Портабельный CLI-скилл для [FinanceMarker.ru](https://financemarker.ru/api/)
(фундаментальные данные по публичным компаниям — отчётность, мультипликаторы,
дивиденды, инсайдеры, идеи аналитиков). Агент opencode вызывает команды через
`bash`, получает JSON и работает с данными как с обычными структурами.

## Возможности

- Список компаний и подробная карточка по тикеру
- Дивиденды (upcoming / past)
- Календарь корпоративных событий и раскрытие
- Сделки инсайдеров
- Идеи аналитиков (лидерборд + детали)
- Сводные мультипликаторы (P/E, EV/EBITDA, ROE, дивдоходность…)
- Локальный SQLite в `.fmc-cache/fmc.db` (отдельный от `.bcs-cache/`) для
  последних снэпшотов company overview и метаданных тикеров

## Установка

```bash
cd .opencode/skills/financemarker-api
pip install -r requirements.txt
cp .env.example .env  # и вписать FM_API_TOKEN
```

## Первый запуск

```bash
fmc token                         # проверить квоту
fmc stocks --limit 10             # топ-10 компаний
fmc stock MOEX:LKOH --include summary,ratios
fmc dividends --mode upcoming --limit 5
```

## Структура

```
financemarker/    пакет с логикой
fmc.py            CLI (argparse + subcommands)
fmc               unix-обёртка
SKILL.md          описание скилла (читает opencode)
tests/            юнит-тесты
```

Подробности — в `SKILL.md` и в корневом `AGENTS.md`.
