# Contributing to FinAdvisor

## Development Setup

1. Clone the repository
2. Install Python 3.11+ and Node.js 22+
3. Install `uv` package manager: `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
4. Sync dependencies: `uv sync --group dev --group ml`
5. Install frontend dependencies: `cd web && npm install`
6. Copy `.env.example` to `.env` and configure
7. Run database migrations: `uv run alembic upgrade head`
8. Start development server: `uv run uvicorn src.interfaces.api.server:app --reload`

## Code Quality

### Python

- **Linting**: `ruff check src/`
- **Formatting**: `ruff format --check src/` (auto-fix: `ruff format src/`)
- **Type checking**: `mypy src/`
- **Tests**: `pytest tests/ -v`

### Frontend

- **Linting**: `cd web && npm run lint`
- **Tests**: `cd web && npx vitest run`

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests for your changes
3. Ensure all linting and type checks pass
4. Update documentation if needed
5. Create a PR with a clear description of the changes
6. Ensure CI passes

## Code Conventions

- Follow existing patterns in the codebase
- Use type hints for all public functions
- Write docstrings for modules and public APIs
- Log exceptions with context, never use bare `except: pass`
- Use structlog for structured logging
- Use SQLAlchemy async sessions for API endpoints
- Keep functions focused and modular
- Write tests for new functionality

## Commit Conventions

We follow conventional commits:
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code change without feature/fix
- `test:` — adding or updating tests
- `docs:` — documentation changes
- `chore:` — maintenance tasks
- `security:` — security fixes
