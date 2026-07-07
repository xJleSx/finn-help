# ADR-001: Package Decomposition Strategy

**Status:** Accepted
**Date:** 2026-07-06

## Context
Large single-module files (telegram.py, models.py, cli.py, etc.) exceeded 1000+ lines and became difficult to maintain, test, and navigate.

## Decision
Split large files into domain-oriented packages with backward-compatible re-exports:
- `telegram.py` → `telegram/` (6 files: bot, callbacks, conversations, handlers/{account,analysis,market,misc,portfolio}, messages)
- `db/models.py` → `db/models/` (10 files: base, instrument, portfolio, user, news, risk, social, paper, misc)
- `cli/commands.py` → `cli/commands/` (4 files: data, analysis, trading, misc)
- `llm/prompts.py` → `llm/prompts/` (3 files: analysis, report, question)
- `interfaces/nlq.py` → `interfaces/nlq/` (constants, engine)
- `portfolio/allocator.py` → `portfolio/allocator/` (profiles, engine)

## Consequences
- Backward compatibility maintained via `__init__.py` re-exports
- Easier to navigate and test individual modules
- Clear separation of concerns per submodule
