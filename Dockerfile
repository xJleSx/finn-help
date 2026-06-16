FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple

FROM python:3.13-slim

RUN groupadd -r finn && useradd -r -g finn finn

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY entrypoint.sh .

RUN mkdir -p /app/data && chown -R finn:finn /app/data
RUN chmod +x entrypoint.sh

VOLUME /app/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

USER finn
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
