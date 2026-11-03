#!/usr/bin/env bash
# Check for missing migrations, then run one service's test suite, in a
# throwaway container from its built image.
# Needs the core stack's Postgres and Redis to be up (`make up`).
#   scripts/test-service.sh post
set -euo pipefail

service="$1"
env_file=".env.test-${service}"
trap 'rm -f "$env_file"' EXIT
# `docker run --env-file` keeps inline comments, so strip them.
sed -E 's/[[:space:]]+#.*$//' .env | grep -E '^[A-Z0-9_]+=' > "$env_file"

network="--network tara_default"
pytest_args="--create-db"
if [ "$service" = "bff" ]; then
  # Not a Django service: no database.
  network=""
  pytest_args=""
fi

# shellcheck disable=SC2086
MSYS_NO_PATHCONV=1 docker run --rm $network --env-file "$env_file" \
  -e POSTGRES_HOST=postgres -e REDIS_URL=redis://redis:6379/15 -e RABBITMQ_URL= \
  -e PIP_CONSTRAINT= --user root --entrypoint sh -e PYTEST_ARGS="$pytest_args" "tara/${service}:dev" -ec '
    pip install -q --root-user-action=ignore -r requirements-dev.txt pytest-asyncio
    if [ -d "$(ls -d */migrations 2>/dev/null | head -1)" ]; then
      python manage.py makemigrations --check --dry-run
    fi
    python -m pytest -q --no-header -p no:cacheprovider -W ignore $PYTEST_ARGS'
