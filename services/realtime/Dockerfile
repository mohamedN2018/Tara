# Realtime gateway image (ASGI/Daphne). Build context = repo root.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Exact versions for every dependency (regenerate with `make lock`).
COPY constraints.txt /opt/tara/constraints.txt
ENV PIP_CONSTRAINT=/opt/tara/constraints.txt

COPY libs /opt/tara/libs
RUN pip install \
    /opt/tara/libs/tara_common \
    /opt/tara/libs/tara_events \
    /opt/tara/libs/tara_resilience \
    /opt/tara/libs/tara_observability

COPY services/realtime/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/realtime/ /app/

RUN useradd --create-home --uid 10009 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# Serve HTTP (health/metrics) + WebSocket via Daphne (ASGI).
# Oversized WebSocket frames are refused from the header, before buffering
# (the consumer's own 16 KiB check only runs on a complete message).
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", \
     "--websocket-max-message-size", "65536", "--websocket-max-frame-size", "65536", \
     "config.asgi:application"]
