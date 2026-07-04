---
description: Fetch MOEX market data via financemarker-api — fundamentals, dividends, ratios, analyst ideas, corporate events
---

Use the financemarker-api CLI at `.opencode/skills-tools/financemarker-api/`. The CLI is `fmc`.

Available subcommands:
- `fmc token` — check API quota
- `fmc stocks --limit N` — list companies
- `fmc stock MOEX:TICKER --include summary,ratios` — company card with fundamentals
- `fmc dividends --mode upcoming/past --limit N` — dividends
- `fmc events --mode upcoming/past --limit N` — corporate events
- `fmc ratios MOEX:TICKER` — key multiples (P/E, EV/EBITDA, ROE, div yield)
- `fmc research --mode leaders/detail` — analyst ideas

First ensure dependencies are installed (check for .venv or run `pip install -r requirements.txt` from the tool directory). Then run the requested command.

User request: $ARGUMENTS
