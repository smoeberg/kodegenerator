#!/bin/sh
set -eu

python -m scripts.validate_runtime_environment

if [ "${DOR_RUN_MIGRATIONS:-0}" = "1" ]; then
  if [ ! -f /app/alembic.ini ] || [ ! -d /app/alembic ]; then
    echo "migration configuration is missing" >&2
    exit 1
  fi
  python -m alembic upgrade head
fi

if [ "${DOR_BOOTSTRAP_ARTIFACT_BUCKET:-0}" = "1" ]; then
  python -m scripts.bootstrap_artifact_store
fi

if [ "${DOR_BOOTSTRAP_WORKER_IDENTITY:-0}" = "1" ]; then
  python -m scripts.bootstrap_worker_identity
fi

exec "$@"
