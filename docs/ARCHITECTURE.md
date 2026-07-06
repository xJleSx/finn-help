# Architecture

## Project Structure

```
finn-help/
├── src/
│   ├── analysis/          # Analytics, backtesting, ML models
│   │   ├── backtest.py    # Backtesting engine
│   │   ├── metrics.py     # Shared metrics helpers
│   │   ├── ml/            # Price targets, ML coordinator
│   │   └── personal_backtest.py
│   ├── cli/               # CLI interface (commands + __init__)
│   ├── constants.py       # Shared constants (ACTION_EMOJI, etc.)
│   ├── db/                # Database layer
│   │   ├── models/        # SQLAlchemy models (10 files)
│   │   └── queries.py     # Shared query helpers
│   ├── interfaces/        # Entry points
│   │   ├── nlq/           # Natural language query (constants + engine)
│   │   ├── api.py
│   │   └── telegram/      # Telegram bot (6 files)
│   ├── llm/
│   │   └── prompts/       # LLM prompts (analysis, report, question)
│   ├── notifications/
│   ├── portfolio/
│   │   └── allocator/     # Portfolio allocation (profiles + engine)
│   ├── scheduler/
│   ├── signals/
│   ├── tests/             # 73 test files
│   └── trading/
├── docs/                  # Documentation
├── web/                   # Web frontend
├── pyproject.toml
└── README.md
```

## Key Design Decisions

- **Package decomposition**: Large files split into packages with backward-compatible imports via `__init__.py` re-exports
- **Metrics deduplication**: Shared metrics in `analysis/metrics.py` to avoid duplication across backtesting modules
- **Query helpers**: Shared DB queries in `db/queries.py` to centralize common instrument/price lookups
- **Database models**: Split into domain-specific files (instrument, portfolio, user, news, risk, social, paper, misc)

## Import Conventions

All public symbols are re-exported from package `__init__.py` files. Old single-module imports continue to work:

```python
# Both work after refactoring:
from src.portfolio.allocator import PortfolioAllocator  # Old style
from src.portfolio.allocator.engine import PortfolioAllocator  # New style
```
