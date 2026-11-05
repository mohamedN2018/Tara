#!/usr/bin/env bash
# Media container entrypoint. Web role runs migrations + ensures the bucket.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${TARA_ENV:-}" = "production" ]; then
  python manage.py check --deploy --fail-level ERROR
fi

# Only the web server migrates: workers share the env (and its RUN_MIGRATIONS)
# but run celery or manage.py commands, so they never race the migration.
if [ "${RUN_MIGRATIONS:-false}" = "true" ] && [ "${1:-}" = "gunicorn" ]; then
  echo "[media] migrate"
  python manage.py migrate --noinput
  echo "[media] ensure bucket"
  python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup(); from media_app.storage import ensure_bucket; ensure_bucket()" || true
fi

exec "$@"
