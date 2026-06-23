# Identity service image.
# Build context = repo root (so we can COPY the shared libs/).
#   docker build -f services/identity/Dockerfile -t tara/identity .
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is used by the container HEALTHCHECK only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Shared kernel (changes rarely -> cached layer)
COPY libs /opt/tara/libs
RUN pip install \
    /opt/tara/libs/tara_common \
    /opt/tara/libs/tara_events \
    /opt/tara/libs/tara_resilience \
    /opt/tara/libs/tara_observability

# 2) Service deps
COPY services/identity/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# 3) Service code
COPY services/identity/ /app/

# Non-root runtime user; owns the writable keys dir.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.keys /app/staticfiles \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
