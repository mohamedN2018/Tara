# 06 — Infrastructure Plan

Covers local development (Docker Compose), production (Kubernetes-ready),
observability, CI/CD, and secrets. Concrete manifests/compose files are
*created in Phase 1* — this fixes the shape.

## 1. Proposed repository layout (monorepo)

```
tara/
├─ docs/                      # this documentation
├─ services/
│  ├─ identity/               # Django project (own settings, Dockerfile, tests)
│  ├─ profile/
│  ├─ social_graph/
│  ├─ post/
│  ├─ feed/
│  ├─ media/
│  ├─ chat/
│  ├─ realtime/               # Django Channels (ASGI)
│  ├─ notification/
│  ├─ search/
│  ├─ marketplace/
│  ├─ ads/
│  ├─ moderation/
│  ├─ admin/
│  ├─ analytics/
│  └─ bff/                    # thin aggregation/edge API
├─ libs/                      # shared kernel (installed editable into each service)
│  ├─ tara_common/            # auth middleware, error format, pagination, logging
│  ├─ tara_events/            # envelope, EventPublisher, outbox relay, schemas
│  ├─ tara_resilience/        # timeouts, retries, circuit breaker, idempotency
│  └─ tara_observability/     # OTel setup, structured logging, metrics helpers
├─ frontend/
│  └─ web/                    # Vue 3 + Vite + Pinia + Tailwind
├─ infra/
│  ├─ compose/                # docker-compose.*.yml + service profiles
│  ├─ k8s/                    # base + overlays (dev/staging/prod) — Kustomize
│  ├─ traefik/                # edge config
│  └─ observability/          # Prometheus, Grafana dashboards, Loki, OTel collector
├─ .github/workflows/         # CI/CD pipelines
├─ Makefile                   # dev commands (up, migrate, test, lint, seed)
└─ README.md
```

> Each `services/*` is independently buildable & deployable. `libs/*` is the
> versioned shared kernel kept deliberately thin (see [ADR-002](09-decision-log.md)).

## 2. Local development (Docker Compose)

Compose with **profiles** so you run only what you need:

| Profile | Brings up |
|---------|-----------|
| `core` | Postgres (one container, multiple DBs via init script), Redis, RabbitMQ, MinIO, Mailpit, identity, profile, graph, post, feed, bff, Traefik |
| `media` | + media service + Celery media/file workers |
| `chat` | + realtime (Channels) + chat |
| `search` | + OpenSearch + search service + indexer |
| `market` | + marketplace |
| `ads` | + ads + (Redpanda for firehose, optional) |
| `full` | everything |
| `observability` | Prometheus, Grafana, Loki, OTel collector |

Backing services in dev:
- **PostgreSQL** — single instance, one database per context (init SQL creates
  `identity_db`, `profile_db`, …). Mirrors prod's logical separation cheaply.
- **Redis** — cache, channel layer, rate-limit buckets, presence/typing.
- **RabbitMQ** — events + Celery (management UI exposed).
- **MinIO** — S3-compatible object storage; console exposed.
- **Mailpit** — captures outbound email (verification/reset) for inspection.
- **OpenSearch** — optional profile.
- **Redpanda** — optional, Kafka-compatible firehose for ads/analytics.

Documented commands (Makefile targets, indicative — built in Phase 1):
```bash
make up                 # docker compose --profile core up -d
make up-full            # everything
make migrate            # run migrations across all services
make seed               # load realistic synthetic dev data (never fake "prod" data)
make test               # run all service test suites
make test SERVICE=post  # one service
make logs SERVICE=chat
make down
```

## 3. Production (Kubernetes-ready)

- **One Deployment per service** (true microservices, see doc 02 §2), each with its own HPA
  (CPU/RAM + custom metrics: queue depth for workers, active connections for
  realtime), `PodDisruptionBudget`, resource requests/limits (bulkhead), and
  liveness/readiness/startup probes.
- **Ingress:** Traefik (or Nginx Ingress) → BFF/services. TLS via cert-manager.
  **WAF** in front (cloud WAF or ModSecurity).
- **Stateful backing services:** managed where possible — managed PostgreSQL
  (per-context databases/instances), managed Redis, managed object storage + CDN
  (CloudFront/Cloudflare), managed RabbitMQ/Kafka. Self-host only what must be.
- **Config & secrets:** ConfigMaps for non-secret config; secrets via a secrets
  manager (Vault / cloud Secrets Manager) injected as env or mounted — **never**
  baked into images or committed.
- **Migrations:** run as a pre-deploy Kubernetes `Job` per service
  (`migrate` before rolling out new pods). Backward-compatible migration
  discipline (expand/contract) so rolling deploys never break running pods.
- **Deployments:** rolling by default; blue/green or canary for risky changes
  via the ingress/labels. Each service versioned & released independently.
- **Environments:** `development`, `staging`, `production` as Kustomize overlays
  with separate clusters/namespaces, data, and secrets.

## 4. Edge / gateway / BFF

- **Traefik (edge):** TLS termination, routing by path/host to services,
  global per-IP rate limiting, request-id injection, basic WAF rules,
  compression.
- **BFF (thin):** verifies user JWT (JWKS), composes client-shaped responses
  (e.g. feed page + author snapshots), applies per-user rate limits, and is the
  *only* tier that fans out to multiple services for a single screen. Internal
  service endpoints are never exposed directly to clients.
- Circuit breakers + cached fallbacks live in the BFF for the degradation matrix.

## 5. Observability (baseline from Phase 1)

| Pillar | Tooling | Notes |
|--------|---------|-------|
| **Logs** | Structured JSON → Loki (or ELK) | every log carries `request_id`, `trace_id`, `service`, `account_id?`. **No secrets/PII bodies.** |
| **Metrics** | Prometheus + Grafana | RED metrics per service, queue depth, socket counts, DB pool, cache hit rate, outbox lag |
| **Tracing** | OpenTelemetry → (Tempo/Jaeger) | trace propagates across HTTP + events (correlation_id ↔ trace) |
| **Errors** | Sentry | per service, release-tagged |
| **Alerting** | Alertmanager | see thresholds below |

**Alert on:** elevated error rate (per service), p95 latency breach, queue
backlog / outbox publish lag, DLQ growth, WebSocket connection saturation,
failed Celery jobs, DB health/replication lag, storage failures, auth-abuse
spikes (failed logins, token reuse), feature-flag-disabled core module.

## 6. CI/CD baseline

- **CI (GitHub Actions):** on PR — lint (ruff/black/mypy; eslint/prettier),
  unit + integration tests per changed service (path-filtered), event-schema
  validation, contract tests, build Docker images, security scans (dependency
  audit, image scan, secret scan), OpenAPI generation/diff.
- **CD:** on merge to `main` → build & push images → deploy to **staging**
  automatically; **production** deploy gated by manual approval. DB migration
  Jobs run before rollout. Smoke tests post-deploy; auto-rollback on failed
  health checks.
- **Per-service pipelines** (path filters) so unrelated services don't rebuild.

## 7. CDN & media delivery

- Public media served via CDN in front of object storage; private media via
  **short-lived signed URLs** issued by the Media service after object-level
  auth. Upload also via signed URLs (client → storage directly), keeping large
  payloads off the API tier.
- SSRF-safe rules for any server-side media fetch (link previews): allowlist,
  no internal IP ranges, size/time limits.

## 8. Security baseline (infra-level; full policy in doc 08 & the brief §17)

- mTLS between services in-cluster; internal endpoints not exposed at edge.
- Network policies restrict pod-to-pod traffic to declared dependencies.
- Secrets only via secret manager; rotation supported.
- Security headers + CSP at the edge; CORS allowlist; secure cookies for web.
- Per-service least-privilege DB users and broker credentials.
- Backups encrypted; restore drills scheduled (DR plan in doc 07).

## 9. Cost/operability note

Running all 17 microservices locally at once is heavy; **Compose profiles**
(§2) keep day-to-day dev light — you run only the services you're working on
while preserving the production topology (one deployment per service). Strict
phasing also means most services don't exist yet until their phase. This is a
direct consequence of [ADR-001](09-decision-log.md) + [ADR-002](09-decision-log.md).
