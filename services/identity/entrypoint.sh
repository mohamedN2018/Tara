#!/usr/bin/env bash
# Identity container entrypoint.
# - waits for Postgres
# - (web role only) generates JWT keys, runs migrations, then execs the CMD
# Workers set RUN_MIGRATIONS=false to avoid migration races.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[identity] ensuring JWT signing keys"
  python manage.py ensure_jwt_keys

  # Phase 1 dev convenience: generate migrations from models on first boot so the
  # schema always matches. For staging/prod, commit migrations and set
  # RUN_MAKEMIGRATIONS=false (see docs/architecture/phase-1 report).
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[identity] makemigrations"
    python manage.py makemigrations identity --noinput
  fi

  echo "[identity] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
