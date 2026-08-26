#!/bin/sh
set -eu

if [ -f /app/alembic.ini ] && [ -d /app/alembic ]; then
  python -m alembic upgrade head
fi

exec "$@"
