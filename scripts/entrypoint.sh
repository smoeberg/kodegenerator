#!/bin/sh
set -eu

if [ "${DOR_RUN_MIGRATIONS:-0}" = "1" ]; then
  if [ ! -f /app/alembic.ini ] || [ ! -d /app/alembic ]; then
    echo "migration configuration is missing" >&2
    exit 1
  fi
  python -m alembic upgrade head
fi

if [ "${DOR_BOOTSTRAP_ARTIFACT_BUCKET:-0}" = "1" ]; then
  python /app/scripts/bootstrap_artifact_store.py
fi

if [ "${DOR_BOOTSTRAP_WORKER_IDENTITY:-0}" = "1" ]; then
  python /app/scripts/bootstrap_worker_identity.py
fi

exec "$@"
