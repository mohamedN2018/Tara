#!/usr/bin/env bash
# Identity container entrypoint.
# - waits for Postgres
# - (web role only) generates JWT keys, runs migrations, then execs the CMD
# Workers set RUN_MIGRATIONS=false to avoid migration races.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${TARA_ENV:-}" = "production" ]; then
  python manage.py check --deploy --fail-level ERROR
fi

# Only the web server migrates: workers share the env (and its RUN_MIGRATIONS)
# but run celery or manage.py commands, so they never race the migration.
if [ "${RUN_MIGRATIONS:-false}" = "true" ] && [ "${1:-}" = "gunicorn" ]; then
  echo "[identity] ensuring JWT signing keys"
  python manage.py ensure_jwt_keys

  echo "[identity] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
