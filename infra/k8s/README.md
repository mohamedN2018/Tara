# Tara — Kubernetes manifests (Kustomize)

Production deployment manifests realizing ADR-001 (each service independently
deployable, horizontally scalable). Compose remains the local-dev path; this is
the production path.

## Layout

```
base/                 generic, service-agnostic WEB-tier resources
  deployment.yaml     web (component: api): non-root, read-only rootfs, probes, limits, topology spread
  service.yaml        ClusterIP :80 -> :8000, selects component: api only
  hpa.yaml            HPA v2: CPU 70% / mem 80%, 2..10 replicas
  pdb.yaml            PodDisruptionBudget minAvailable: 1 (component: api)
  serviceaccount.yaml token automount disabled
  networkpolicy.yaml  default-deny ingress; allow tara pods + monitoring ns
components/           opt-in async workloads (shared, DRY)
  worker/             celery -A config worker -B (outbox drain) — singleton (component: worker)
  consumer/           manage.py consume_events — competing, idempotent, 2 replicas (component: consumer)
cluster/              install-once, cluster-scoped resources
  namespace.yaml      the `tara` namespace
  cluster-issuer.yaml cert-manager Let's Encrypt issuers (staging + prod)
  secret-store.example.yaml       External Secrets ClusterSecretStore (template)
overlays/<svc>/externalsecret.example.yaml   per-service ESO ExternalSecret (all 14)
overlays/             one per service — all 14 present:
  identity/ profile/ graph/ media/ post/ feed/ chat/ marketplace/
  notification/ search/ moderation/ admin/ ads/   (gunicorn/WSGI, with DB)
  realtime/           ASGI/daphne, NO DB, /ws ingress, Redis channel layer
  <each>/
    kustomization.yaml namePrefix/labels/image + resources
    configmap.yaml     non-secret env (service's own *_DB_*, *_ALLOWED_HOSTS, ...)
    secret.example.yaml placeholder secrets (REPLACE_ME — never apply as-is)
    migrate-job.yaml   pre-rollout `manage.py migrate` Job (omitted for realtime)
    ingress.yaml       NGINX ingress: TLS redirect + security headers + rate limit
    patch-deployment.yaml service web command (gunicorn, or daphne for realtime)
```

All overlays reuse `base/` unchanged and build with `kubectl kustomize`.

### Workloads per service (mirrors compose)

An overlay opts into async workloads via `components:`. The web Deployment +
migrate Job come from the base/overlay; worker/consumer come from components.

| service | web | worker (outbox) | consumer | notes |
|---|:--:|:--:|:--:|---|
| identity | ✓ | ✓ | — | emits only |
| profile, graph, post, feed, chat, marketplace, notification, moderation | ✓ | ✓ | ✓ | emit + consume |
| media, ads | ✓ | ✓ | — | emit only |
| search | ✓ | ✓ | ✓ | indexer; the worker relays `search.queried` only (Tara Intelligence WP 8.7-B2) |
| admin | ✓ | — | — | web only |
| realtime | ✓ | — | bridge | DB-less; inline `bridge` Deployment (1 replica), ASGI |

> The `worker` runs `celery worker -B` as a **singleton** (embedded beat must not
> double-schedule the outbox drain). The `realtime` bridge is a single replica to
> avoid duplicate socket delivery; DB consumers run 2 (idempotent).

## Build / apply

```bash
# Render (validate) one overlay — no cluster needed:
kubectl kustomize infra/k8s/overlays/identity

# Validate all overlays:
for d in infra/k8s/overlays/*/; do kubectl kustomize "$d" >/dev/null && echo "ok $d"; done

# Apply one (cluster + real secrets required):
kubectl apply -k infra/k8s/overlays/identity
```

## Adding a NEW service

Copy any existing overlay to `overlays/<svc>`, then change: `namePrefix`,
`commonLabels.app.kubernetes.io/name`, the `images[].newName/newTag`, the
ConfigMap/Secret keys (use the service's own `*_DB_*`, `*_ALLOWED_HOSTS`, etc.),
and the Ingress `paths`/`host`. The base is reused unchanged.

## TLS

`cluster/cluster-issuer.yaml` defines Let's Encrypt issuers; every Ingress is
annotated `cert-manager.io/cluster-issuer: letsencrypt-prod`, so cert-manager's
ingress-shim issues the `tara-api-tls` cert referenced in each Ingress `tls`
block. Requires cert-manager installed in the cluster.

## Secrets

`secret.example.yaml` is a render/dev placeholder only. In production:

1. Install External Secrets Operator and apply `cluster/secret-store.example.yaml`
   (filled in for your backend).
2. Each overlay already ships `externalsecret.example.yaml` — its keys exactly
   match that service's Secret, and its `target.name` is the already-prefixed
   Secret name (e.g. `identity-service-secrets`). Apply it directly
   (`kubectl apply -f overlays/<svc>/externalsecret.example.yaml`) and drop
   `secret.example.yaml` from the overlay's kustomization `resources`.

**Gotcha:** ESO creates the Secret at its literal `target.name` (kustomize's
`namePrefix` is NOT applied to runtime-created secrets), which is why the target
is pre-prefixed. The `tara_common` production-safety deploy check
(`tara.E001..E006`) rejects placeholder/dev values if they ever reach a
`DEBUG=false` process.

## Network policy

The base NetworkPolicy default-denies both directions. Ingress: Tara pods + the
monitoring namespace (:8000). Egress: DNS, sibling Tara pods, monitoring (OTEL),
and ports 5432/6379/5672/9200/443 (managed stores + HTTPS for S3/secret-manager/
ACME). Tighten the egress CIDRs once the managed endpoints are known.

## Migrations

Migrations run as the pre-rollout `migrate` Job (Argo PreSync hook or a CI step),
**not** at container boot — replacing the dev-only boot-time migration behaviour.
