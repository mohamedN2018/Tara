# Phase 9 — Scale, Security & Production Readiness (Report)

> Status: **implemented & verified** (artifact-level). Hardens the platform for
> production: a shared **production-safety deploy gate** wired into all 14
> services, **edge gateway hardening** (security headers + rate limiting),
> **Kubernetes/Kustomize** deployment manifests realizing ADR-001's
> "independently deployable + horizontally scalable" claim, **Prometheus
> alerting**, and a **production env/secrets/migration** story. No application
> features were added; this phase is operational hardening only.

---

## 1. Architecture changes

- **Production-safety is now enforced, not just documented.** A shared deploy
  check in the kernel (`tara_common.checks`) fails `manage.py check --deploy`
  when a service runs with `DEBUG=False` and any secret is still a dev default /
  `REPLACE_ME` placeholder, `ALLOWED_HOSTS` is `*`/empty, or CORS allows all
  origins with credentials. Wired into **all 14 services** via `AppConfig.ready()`.
  This makes the brief's "no hard-coded secrets" rule a hard gate.
- **Edge security moved to the gateway.** Traefik now applies a
  `tara-secure-headers` middleware (HSTS, nosniff, frame-deny, referrer-policy,
  permissions-policy, server-token stripping) and a `tara-ratelimit` middleware
  to **all** routed traffic via the `web` entrypoint — defined declaratively in a
  Traefik **file provider** (`infra/traefik/dynamic/`), not scattered per service.
  Auth endpoints keep their in-app DRF throttles as defence-in-depth.
- **A real production deploy path.** `infra/k8s/` adds a Kustomize **base**
  (hardened Deployment, Service, HPA, PDB, NetworkPolicy, ServiceAccount) plus a
  worked **identity overlay**. This is the concrete form of ADR-001: each service
  is its own Deployment + HPA (2→10 replicas on CPU/mem), with liveness/readiness/
  startup probes hitting the existing `/healthz` + `/readyz`, non-root read-only
  containers, resource requests/limits, and a pre-rollout migration Job (replacing
  dev-only boot-time migration).
- **Alerting closes the observability loop.** Prometheus already scraped
  `/metrics`; Phase 9 adds `alerts.yml` (availability, error-rate, latency,
  outbox backlog, K8s crashloop/HPA-maxed) and wires `rule_files`.

## 2. Files created / changed

- **Shared kernel:** `libs/tara_common/tara_common/checks.py` (new) — pure
  `evaluate_production_safety()` + Django `register_checks()`.
- **All 14 services:** `services/*/<app>/apps.py` — `ready()` now calls
  `register_checks()` (identity + 13 others).
- **Test:** `services/identity/identity/tests/test_production_safety.py` (new).
- **Gateway:** `infra/traefik/dynamic/middlewares.yml` (new); `infra/compose/
  docker-compose.yml` — Traefik file provider + entrypoint middlewares + mount.
- **Kubernetes:** `infra/k8s/base/{kustomization,deployment,service,hpa,pdb,
  serviceaccount,networkpolicy}.yaml`, `infra/k8s/overlays/identity/{kustomization,
  configmap,secret.example,migrate-job,ingress,patch-deployment}.yaml`,
  `infra/k8s/README.md` (all new).
- **Observability:** `infra/observability/alerts.yml` (new); `prometheus.yml`
  (+`rule_files`); compose mounts `alerts.yml`.
- **Config:** `.env.production.example` (new); `Makefile` (+`check-deploy`,
  `k8s-build`, `prom-check`).

## 3. Services added / changed

No new runtime services. Behavioural change: **all 14 Django services** now
register the production-safety deploy check (no request-path impact; only affects
`check --deploy` and is a no-op when `DEBUG=True`).

## 4. Database changes

**None.** No models, migrations, or schema changes. Phase 9 changes *how*
migrations are run in production (pre-rollout Job, §1) — not the schema.

## 5. API endpoints

**None added or changed.** Gateway hardening adds response headers and rate
limiting to existing routes; it introduces no new paths.

## 6. Event contracts

**None.** A new alert (`OutboxBacklogGrowing`) *observes* the existing outbox
pipeline via the `tara_outbox_pending_events` gauge but defines no new events.

## 7. Tests / verification

Verified this session with the tools available on the host (`docker`, `kubectl`,
`ruff`, `python`):

- **Production-safety logic** — pure `evaluate_production_safety` exercised
  directly: dev-defaults **and** `REPLACE_ME` placeholders flag errors
  (`tara.E001..E006`) under `DEBUG=False`; a hardened config yields **zero**
  findings (no false positives); `DEBUG=True` yields nothing. ✓
- **Lint/format** — `ruff check` + `ruff format --check` clean on the new module,
  all 14 edited `apps.py`, and the test. ✓
- **Kubernetes** — `kubectl kustomize infra/k8s/overlays/identity` builds (exit 0);
  verified name-prefixing and that **all** references rewired correctly
  (`envFrom`→`identity-service-config`/`-secrets`, `serviceAccountName`,
  HPA `scaleTargetRef`, Ingress backend → `identity-service`), image transformed,
  and the gunicorn patch applied. ✓
- **Gateway / compose** — `docker compose config` valid after the Traefik +
  Prometheus edits. ✓
- **Prometheus** — dockerized `promtool check rules` (8 rules) and
  `promtool check config` (config valid, 1 rule file found) both pass. ✓
- **Traefik dynamic config** — `middlewares.yml` parses as valid YAML. ✓

**Not run this session (honest):** the Django-wrapper test
(`test_production_safety.py`) is committed and runs in the per-service pytest
harness/CI, but was **not executed here** because this host's Python lacks the
service virtualenv (Django). Its pure-logic core *was* verified directly. No new
backend pytest run was performed for Phase 9 (no app code changed).

## 8. Commands

```bash
make check-deploy     # Django --deploy checks incl. the tara production-safety gate
make k8s-build        # kubectl kustomize infra/k8s/overlays/identity (render/validate)
make prom-check       # dockerized promtool check rules
kubectl apply -k infra/k8s/overlays/identity   # (needs a cluster + real secrets)
# per service test (CI / with venv):
cd services/identity && pytest -q identity/tests/test_production_safety.py
```

## 9. Risks / limitations (honest)

- **K8s overlays exist for all 14 services AND their async workloads** (added
  after the initial gate): the web Deployment + pre-rollout migrate Job, plus
  Celery `worker` (outbox drain, singleton) and `consume_events` `consumer`
  (competing, idempotent) via shared Kustomize **components**, matching exactly
  what compose runs per service (see `infra/k8s/README.md` matrix). `realtime` is
  a DB-less ASGI special case with an inline single-replica `bridge`. The web
  Service selects `component: api` only, so workers/consumers never receive HTTP.
  All 14 build with `kubectl kustomize` and selectors were parsed-verified.
- **Manifests validated by render, not by a live cluster.** `kubectl kustomize`
  proves they build and references resolve; there was **no** `apply` or
  server-side dry-run against a real cluster, and no load/chaos testing.
- **Django-wrapper deploy-check test not executed this session** (no service
  venv on this host); pure logic verified instead (§7).
- **Secrets manager wiring provided for all 14 services**: a cluster
  `ClusterSecretStore` template + a per-overlay `externalsecret.example.yaml`
  whose keys are generated to **exactly match** each service's Secret and whose
  `target.name` is the pre-prefixed Secret name (the kustomize↔ESO gotcha,
  documented). These are standalone (applied directly, not in the kustomization),
  so overlays still render with `secret.example.yaml` for dev; the prod swap is a
  documented one-liner per service.
- **TLS via cert-manager is wired** (`cluster/cluster-issuer.yaml` + all 14
  ingresses annotated `cert-manager.io/cluster-issuer`). Assumes cert-manager is
  installed in the cluster.
- **NetworkPolicy now locks egress too** (DNS + Tara pods + monitoring + data-store
  ports + 443). Egress to managed stores is by **port to any IP** — tighten to real
  CIDRs once endpoints are known.
- **CI now validates the Phase 8/9 artifacts** — added `frontend` (npm ci + build)
  and `manifests` (compose config + `kubectl kustomize` over all overlays/cluster +
  `promtool check config`) jobs to `.github/workflows/ci.yml`. The existing
  `identity-tests` job already runs the new `test_production_safety.py`. **Not
  executed here** — workflow YAML validated (parse + structure) only; a real
  GitHub Actions run is needed to confirm end-to-end.
- **Kustomize uses `commonLabels`** (chosen for broad version compatibility);
  current kustomite emits a deprecation warning — benign, build is clean.
- **The Phase 8 → live-stack E2E integration pass is still outstanding** (it was
  flagged in Phase 8 as the bridge; Phase 9 focused on hardening, not E2E).

## 10. Rollback notes

- All changes are additive/config-level and revert cleanly:
  - Remove the `register_checks()` blocks (or it is inert when `DEBUG=True`).
  - Revert the Traefik `command`/volume lines + delete `infra/traefik/` to drop
    gateway middlewares.
  - Delete `infra/k8s/` — no effect on the running compose stack.
  - Revert `prometheus.yml` `rule_files` + the `alerts.yml` mount + delete
    `infra/observability/alerts.yml`.
- No data migrations → nothing to roll back at the DB layer.

## 11. Completion checklist

- [x] Production-safety deploy check in shared kernel (pure + Django wrapper)
- [x] Wired into all 14 services' `AppConfig.ready()`
- [x] Unit test committed (pure logic verified this session; wrapper runs in CI)
- [x] Gateway security headers + rate limit (Traefik file provider) — compose valid
- [x] Kustomize base (Deployment/Service/HPA/PDB/NetworkPolicy/SA)
- [x] **Overlays for all 14 services** (12 WSGI+DB, admin/marketplace/notif DB-prefix
      quirks handled, + DB-less ASGI realtime) — each builds with `kubectl kustomize`
- [x] Probes (`/healthz` `/readyz`), non-root read-only containers, resource limits
- [x] Pre-rollout migration Job (replaces boot-time migration; omitted for realtime)
- [x] K8s async workloads — worker/consumer components + realtime bridge, per-service
      matrix matching compose; web Service selects `component: api` only (parsed-verified)
- [x] Prometheus alert rules (8) + `rule_files` wired — promtool valid
- [x] `.env.production.example` (no dev defaults) + secrets/migration docs
- [x] Make targets `check-deploy` / `k8s-build` / `prom-check`
- [x] TLS via cert-manager (ClusterIssuers + all 14 ingresses annotated)
- [x] Egress NetworkPolicy lockdown (DNS/Tara/monitoring/data-stores/443)
- [x] External Secrets: ClusterSecretStore + per-service `externalsecret.example.yaml`
      for all 14 (keys match each Secret; target pre-prefixed) — YAML-validated
- [x] CI jobs `frontend` (build) + `manifests` (compose/kustomize/promtool) added
- [ ] **Live-cluster apply / load test** — deferred (validated by render only)
- [ ] **Phase 8 → live-stack E2E integration pass** — still outstanding (blocked here
      by the in-container pip/TLS image-build constraint)

---

### Project status (Phases 0–9)

Backend feature-complete (Phases 0–7), web frontend built (Phase 8), production
hardening in place (Phase 9). **Still deliberately NOT built** (per the standing
rule, never claimed otherwise): no end-to-end encryption, no mobile apps, no real
payments/shipping (marketplace shows an explicit "not enabled" notice). Remaining
engineering before a real launch: roll the K8s overlays to all services,
integration-test against a live cluster, wire a secrets manager + TLS, and run the
Phase 8 E2E pass.

### STOP — awaiting approval

Reply **"كمل"** to continue with any of the deferred items above (e.g. the
remaining K8s overlays, or the Phase 8 ↔ live-stack E2E integration pass), or
tell me which to prioritize.
