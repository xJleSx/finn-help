FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv venv && uv pip install hatchling --index-url https://pypi.org/simple && uv sync --no-dev --frozen --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple

FROM python:3.13-slim

RUN groupadd -r finn && useradd -r -g finn finn
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY src/ src/

RUN mkdir -p /app/data && chown -R finn:finn /app/data
VOLUME /app/data

USER finn
EXPOSE 8000

CMD ["uvicorn", "src.interfaces.api.server:app", "--host", "0.0.0.0", "--port", "8000"]