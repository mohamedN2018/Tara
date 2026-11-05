#!/usr/bin/env bash
# Profile container entrypoint. Web role runs migrations; workers/consumers skip.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${TARA_ENV:-}" = "production" ]; then
  python manage.py check --deploy --fail-level ERROR
fi

# Only the web server migrates: workers share the env (and its RUN_MIGRATIONS)
# but run celery or manage.py commands, so they never race the migration.
if [ "${RUN_MIGRATIONS:-false}" = "true" ] && [ "${1:-}" = "gunicorn" ]; then
  echo "[profile] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
