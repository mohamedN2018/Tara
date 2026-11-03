#!/usr/bin/env bash
# Marketplace container entrypoint. Web role runs migrations + seeds categories.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${TARA_ENV:-}" = "production" ]; then
  python manage.py check --deploy --fail-level ERROR
fi

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[marketplace] migrate"
  python manage.py migrate --noinput
  echo "[marketplace] seed categories"
  python manage.py seed_categories || true
fi

exec "$@"
