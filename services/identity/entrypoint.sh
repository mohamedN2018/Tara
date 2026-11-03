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

  echo "[identity] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
