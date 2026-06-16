#!/bin/sh
set -e

# Wait for PostgreSQL if DATABASE_URL contains postgres
if echo "$DATABASE_URL" | grep -q "postgres"; then
  echo "Waiting for PostgreSQL..."
  host=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
  port=$(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
  : "${host:=db}" "${port:=5432}"
  for i in $(seq 1 30); do
    python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('$host', $port)); s.close()" 2>/dev/null && break
    echo "  waiting for postgres... ($i)"
    sleep 1
  done
  echo "PostgreSQL is ready"
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn src.interfaces.api.server:app --host 0.0.0.0 --port 8000
