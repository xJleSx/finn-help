#!/bin/sh
set -e

# Wait for PostgreSQL if DATABASE_URL contains postgres
if echo "$DATABASE_URL" | grep -q "postgres"; then
  echo "Waiting for PostgreSQL..."
  host=$(python -c "from urllib.parse import urlparse; p=urlparse('$DATABASE_URL'); print(p.hostname or 'db')")
  port=$(python -c "from urllib.parse import urlparse; p=urlparse('$DATABASE_URL'); print(p.port or 5432)")
  for i in $(seq 1 30); do
    python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('$host', $port)); s.close()" 2>/dev/null && break
    echo "  waiting for postgres... ($i)"
    sleep 1
  done
  echo "PostgreSQL is ready"
fi

# Validate required secrets in production
if [ "$FINN_ENV" = "production" ]; then
  if [ -z "$DB_PASSWORD" ] || [ "$DB_PASSWORD" = "finn" ]; then
    echo "ERROR: DB_PASSWORD must be set to a strong value in production"
    exit 1
  fi
  if [ -z "$JWT_SECRET" ]; then
    echo "ERROR: JWT_SECRET must be set in production"
    echo "  Generate: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    exit 1
  fi
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
UVICORN_HOST="${UVICORN_HOST:-0.0.0.0}"
UVICORN_PORT="${UVICORN_PORT:-8000}"
exec uvicorn src.interfaces.api.server:app --host "$UVICORN_HOST" --port "$UVICORN_PORT"
