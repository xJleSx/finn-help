---
name: bcs-trade-api
description: Work with BCS Broker (БКС Мир инвестиций) trade API at https://trade-api.bcs.ru/ — auth by refresh token, view portfolio/limits, get market quotes and instrument reference, place/edit/cancel orders, list trades, and persist portfolio snapshots in a local SQLite. Use ONLY when the user asks about BCS, БКС, their BCS broker account, BCS portfolio, BCS quotes, or BCS orders. Do NOT use for Tinkoff, Finam, or other brokers.
---

# BCS Trade API skill

This skill exposes BCS Broker's HTTP API as a portable Python CLI so that
an opencode agent can call BCS on the user's behalf. The CLI is the
single source of truth — read the [API docs](https://trade-api.bcs.ru/)
whenever you are unsure about an endpoint, payload, or permission.

## When to load me

Load this skill when the user mentions BCS / БКС Мир инвестиций and
wants to:

- check portfolio, limits, cash, positions, or P/L;
- see market quotes or look up an instrument;
- list, place, edit, or cancel orders;
- review trades/fills;
- snapshot the portfolio locally (SQLite) for later comparison.

Do not use for other brokers (Tinkoff, Finam, …) and never place an
order without the user confirming the draft.

## How to invoke

The CLI is `bcs` (a thin wrapper around `bcs.py`) at the project root
or under `.opencode/skills/bcs-trade-api/`. Always pass `--format json`
when the agent will parse the output, `--format human` for the final
user-facing summary.

```bash
bcs auth status
bcs auth login
bcs portfolio --format human
bcs limits --format json
bcs market quote SBER
bcs market search "Газпром"
bcs orders list                           # all orders, last 7 days
bcs orders list --days 30 --side sell     # filter by side
bcs orders list --ticker SBER --status executed
bcs orders place --ticker SBER --side buy --type market --qty 10 --account L01-...
bcs orders cancel <order_id>
bcs trades list                           # all trades, last 7 days
bcs trades list --days 30 --ticker SBER
bcs snapshot save
bcs snapshot list
bcs portfolio --term T0     # default; live positions only
bcs portfolio --term T365  # planned future settlements (debug)
bcs snapshot save --term T0 --label "before-rebalance"

# MOEX ISS (free, 15-min delay, no auth needed)
bcs moex security SBER                    # ISIN, lot, face value, listing level
bcs moex quote SBER                       # market data (delayed 15 min)
bcs moex candles SBER --from 2026-06-01 --till 2026-06-10
bcs moex candles SBER --interval 60       # hourly candles
bcs moex splits --ticker SBER             # split history
bcs moex splits --ticker VTBR             # e.g. VTBR 1:5000 split
```

**`--format` goes BEFORE the subcommand** (global argparse):

```bash
bcs --format json portfolio        # ✅ correct
bcs portfolio --format json        # ❌ will error
```

**PowerShell env var for ad-hoc calls** (when `.env` is not auto-loaded):

```powershell
$env:BCS_REFRESH_TOKEN="..."; python bcs.py --format json portfolio
```

Every command exits with:

- `0` — success
- `2` — invalid request (check flags/args)
- `3` — auth error (token missing/expired; run `bcs auth login`)
- `4` — network or API error (see stderr/log)
- `5` — internal bug

## Safety rules for the agent

1. **Never** read, log, print, or commit `tokens.json` or
   `BCS_REFRESH_TOKEN`. The CLI masks tokens as `***last4`.
2. **Never** run `orders place` or `orders cancel` without first
   showing the user a draft and getting an explicit "yes".
3. If `.env` has `BCS_READ_ONLY=1`, all mutating commands must be
   refused with exit code 2.
4. Treat 401 as "refresh and retry once". Treat 429 as "back off".
5. If the user is on a production account and the env says
   `BCS_SANDBOX=1`, fail loudly — do not silently switch.

## Cash / limits — use `bcs limits`, not `bcs portfolio`

`bcs portfolio` shows **positions only** — it does NOT include cash
balances. To see available RUB/USD/EUR, always call `bcs limits`:

```bash
bcs limits --format json          # full depoLimit + moneyLimits
bcs limits --format human         # table for user
```

`moneyLimits` in the response contains:
- `currencyCode` — RUB / USD / EUR
- `quantity.value` — available cash (what you can spend now)
- `locked` — frozen for pending orders

## Settlement lag — cash vs positions

After a trade executes:
- **Cash** changes **immediately** (visible in `moneyLimits` on the
  next `bcs limits` call).
- **Position quantities** update **after clearing** (T+1 or T+2,
  depending on the instrument and exchange rules).

This means right after placing an order you may see reduced cash but
**unchanged position qty**. Do not panic — it's normal settlement
lag. Wait for the next trading day, then re-check with `bcs portfolio`.

## Auth — access token may show `false` on first call

`bcs auth status` may report `"has_access_token": false` on a fresh
start. This is normal — the access token is obtained lazily on the
first real API call (portfolio, limits, etc.). The CLI handles this
automatically.

## MOEX ISS — free market data

The skill includes `bcs moex` commands that call MOEX ISS (Informational
& Statistical Server) directly. **No auth required**, data delayed 15 min.

Use cases:
- `moex security` — ISIN, lot size, face value, listing level for any ticker
- `moex quote` — real-time quote (15-min delay) with bid/ask/OHLCV
- `moex candles` — historical OHLCV for technical analysis (RSI, MACD, MA)
- `moex splits` — split history for correct P/L calculations

MOEX ISS does not require `BCS_REFRESH_TOKEN`. The `moex` commands work
even without `.env`.

## Configuration

`.env` keys (see `.env.example`):

- `BCS_REFRESH_TOKEN` — required, long-lived (90 days).
- `BCS_ACCOUNT` — default account id for orders.
- `BCS_READ_ONLY=1` — disables place/cancel.
- `BCS_SANDBOX=1` — switches base URL to the sandbox (if available).
- `BCS_LOG_LEVEL=INFO` — `DEBUG`/`INFO`/`WARN`/`ERROR`.

## Local state

`.bcs-cache/` is created on first run and contains:

- `tokens.json` (chmod 600) — refresh + last access token.
- `bcs.db` — SQLite with `portfolio_snapshots` and `last_quotes` tables.
- `config.json` — non-secret settings (format, log level, …).

The DB is a **stateful landing pad**, not a response cache: the agent
still hits BCS live on every call. Use `bcs snapshot save` to capture
"what the portfolio looked like at 10:00" for later diffing.

## BCS /portfolio quirk — settlement terms

`/portfolio` returns the same holding **once per settlement term**
(`T0`, `T1`, `T2`, `T365`). Summing them all over-counts by 4×.

The skill always filters to `T0` (the live, tradable position) by
default and additionally deduplicates by `(ticker, classCode, instrumentType)`
to handle instruments listed on multiple boards. Use `--term T1`,
`--term T2` or `--term T365` only for settlement-planning debug; the
default `--term T0` is the right answer for "what do I own right now".

`bcs snapshot save` and `bcs snapshot list` apply the same rule:
`total_rub` is computed on the T0 / deduped view.

## Examples

```bash
# 1) Check auth and refresh
bcs auth status
bcs auth login

# 2) Show portfolio as a table for the user
bcs portfolio --format human

# 3) Get a JSON quote to feed into another tool
bcs market quote SBER --format json | jq '.last'

# 4) Save a snapshot before doing anything risky
bcs snapshot save --label "before-rebalance"

# 5) List today's orders (with filters)
bcs orders list --days 1 --side sell --status executed

# 6) List trades for a specific ticker
bcs trades list --ticker SBER --days 30

# 7) Place a market buy — REQUIRES user confirmation of the draft
bcs orders place --ticker SBER --side buy --type market --qty 10
# CLI prints the draft, then asks: Confirm? [y/N]
```

## Project conventions

See the repo-root `AGENTS.md` for coding style, error handling, and
testing rules. The skill is a regular Python package; `ruff check . &&
ruff format --check .` and `pytest -q` must be green before any commit.
