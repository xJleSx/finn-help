---
description: Broker operations via bcs-trade-api — portfolio, limits, quotes, orders, trades (БКС Мир инвестиций)
---

Use the bcs-trade-api CLI at `.opencode/skills-tools/bcs-trade-api/`. The CLI is `bcs`.

Available subcommands:
- `bcs auth status` — check auth
- `bcs portfolio --format human|json` — current portfolio
- `bcs limits --format json` — cash and limits
- `bcs quote TICKER` — quote snapshot
- `bcs search QUERY` — find instruments
- `bcs orders --active|--all` — active order book
- `bcs trades --limit N` — recent trades

For risk safety, BCS_READ_ONLY=1 is recommended during development. If the user wants to place orders, ask for explicit confirmation first.

First ensure dependencies are installed. Run the requested command.

User request: $ARGUMENTS
