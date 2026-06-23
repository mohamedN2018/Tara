# Media service image. Build context = repo root (to COPY shared libs/).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs /opt/tara/libs
RUN pip install \
    /opt/tara/libs/tara_common \
    /opt/tara/libs/tara_events \
    /opt/tara/libs/tara_resilience \
    /opt/tara/libs/tara_observability

COPY services/media/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/media/ /app/

RUN useradd --create-home --uid 10005 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
