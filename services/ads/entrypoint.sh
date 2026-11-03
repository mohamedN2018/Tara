#!/usr/bin/env bash
# Ads container entrypoint. Web role runs migrations; relay skips.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${TARA_ENV:-}" = "production" ]; then
  python manage.py check --deploy --fail-level ERROR
fi

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[ads] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
