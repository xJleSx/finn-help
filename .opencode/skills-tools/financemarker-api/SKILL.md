---
name: financemarker-api
description: Pull fundamental data for Russian and international public companies from FinanceMarker.ru (отчётность, мультипликаторы, дивиденды, инсайдеры, идеи аналитиков, календарь событий). Use ONLY when the user asks about fundamentals, financial reports, ratios (P/E, EV/EBITDA, ROE), dividends, insider trades, analyst ideas, or company overview for a public company. Do NOT use for live quotes (use the bcs-trade-api skill) or for portfolio holdings.
---

# FinanceMarker API skill

This skill exposes the [FinanceMarker.ru](https://financemarker.ru/api/)
HTTP API as a portable Python CLI. Use it whenever the user wants
**fundamental** data on a public company: reports, ratios, dividends,
insider activity, analyst ideas, or the corporate-events calendar.

## When to load me

Load this skill when the user mentions:

- financial reports, отчётность, МСФО, РСБУ;
- multiples / мультипликаторы: P/E, EV/EBITDA, ROE, P/S, debt/equity;
- dividend history or upcoming dividends, дивиденды, ДД;
- insider trades, сделки инсайдеров;
- analyst ideas, идеи аналитиков, консенсус-прогноз;
- corporate events calendar, раскрытие информации;
- company overview: sector, industry, description, official site.

Do not use for live stock prices or portfolio holdings — that is the
`bcs-trade-api` skill's job.

## How to invoke

```bash
fmc token                  # remaining daily quota + subscription end
fmc stock MOEX:LKOH        # full company payload (all sections)
fmc stock MOEX:SBER --include ratios,summary
fmc stocks --limit 20 --sort-by name --sort-order ASC
fmc dividends --mode upcoming --limit 10
fmc dividends --mode past   --limit 10
fmc calendar                # next corporate events
fmc ideas                   # active analyst ideas
fmc ideas --limit 5 --exchange MOEX
fmc insiders                # latest insider transactions
fmc disclosure              # corporate disclosures
fmc exchanges               # list of supported exchanges
fmc experts                 # analyst leaderboard
fmc operation-metrics       # operating-metric catalogue
```

`--format json` (default) for the agent, `--format human` for the final
user-facing summary. Exit codes: 0 OK, 2 invalid request, 3 auth, 4
API/network, 5 internal.

## Auth

The token lives in `.env` as `FM_API_TOKEN=…`. It is passed in the
query string as `?api_token=…` (FinanceMarker's contract, see swagger).
**Never** read or log the raw token — mask as `***last4`.

## Cross-skill composition

`bcs-trade-api` has a `portfolio` command. The agent can call
`fmc stock MOEX:<ticker> --include summary,ratios` to enrich each
holding with P/E, dividend yield, growth rates, etc. Both skills are
project-local under `.opencode/skills/`.

## Local state

`.fmc-cache/` (created on first run, separate from `.bcs-cache/`):

- `token_status.json` — last `token_info` response (rare, helps catch
  "out of quota" early);
- `company_overview` — most recent `/stocks/{exchange}:{code}` payload
  per ticker (overwritten on every fetch);
- `dividends_recent` — last seen dividends for tickers we've queried;
- `tickers_meta` — lightweight `{exchange, code, name}` index from
  `/stocks` listings for fast name lookup.

The DB is a **stateful landing pad**, not a response cache. Every
command still hits FinanceMarker live; this just records what we saw.

## Rate limits

Default subscription: ~800 requests/day. The skill tracks
`day_limit` from the most recent `token_info` and warns the user when
it drops below 50.

## Safety rules for the agent

1. **Never** read, log, print, or commit `FM_API_TOKEN` or
   `.fmc-cache/`. The CLI masks the token as `***last4`.
2. If `token_info` returns `user_not_found`, the token is missing or
   revoked — fail fast, do not retry.
3. `fmc token` should be the first call in any new session. If the
   remaining daily quota is <50, warn the user.
4. FinanceMarker responses are large (a single `stock` payload can be
   100+ KB). Prefer `--include` to keep responses focused.

## Project conventions

See the repo-root `AGENTS.md` for coding style, error handling, and
testing rules. The skill is a regular Python package; `ruff check . &&
ruff format --check .` and `pytest -q` must be green before any commit.
