# Deploying Tara on Dokploy

One domain, fully automated. Dokploy builds every image, brings the stack up, and
on first boot the platform **creates its databases, generates JWT keys, runs
migrations, and creates the object-storage bucket by itself**. Healthchecks +
`restart: unless-stopped` + request-time DNS in the nginx edge make it
self-healing.

Files involved (already in the repo):
- `docker-compose.dokploy.yml` — the production stack.
- `frontend/web/Dockerfile` + `frontend/web/nginx.conf` — the single-origin edge
  (serves the SPA and reverse-proxies `/api/v1/*` and `/ws/*`).
- `scripts/gen-dokploy-env.sh` — generates strong secrets.

---

## 0. Prerequisites

- A server with **Dokploy** installed (it ships Traefik + automatic Let's Encrypt).
- A **domain** with a DNS `A` record pointing at the server (e.g. `tara.example.com`).
- Server size: this is a true-microservices stack (**~40 containers**). Use at
  least **4 vCPU / 12 GB RAM** for a comfortable demo; 8 GB is the practical floor.

## 1. Generate the environment

From a checkout of this repo (locally or on the server):

```bash
chmod +x scripts/gen-dokploy-env.sh
./scripts/gen-dokploy-env.sh tara.example.com
```

This writes `.env` with a unique strong secret for every service + database +
broker + object store. **Never commit it.** Open the file and copy its contents —
you'll paste it into Dokploy next.

## 2. Create the Dokploy service

1. Dokploy → **Create Project** → inside it **Create Service → Compose**.
2. **Provider:** point it at this Git repository (and branch).
3. **Compose Path:** `docker-compose.dokploy.yml`.
4. **Environment:** paste the entire generated `.env` into the Environment panel.
   Confirm `DOMAIN=tara.example.com` is set there.
5. **Domain:** the compose already carries Traefik labels for `Host(${DOMAIN})`
   on Dokploy's `dokploy-network` with `certresolver=letsencrypt`, so TLS is
   automatic. (If your Dokploy uses a different cert-resolver name, adjust the
   `web` service label.)

## 3. Deploy

Hit **Deploy**. The first build compiles 14 service images + the web image, so it
takes a while. Then, automatically and in order:

- Postgres initializes and **creates every per-service database/role**
  (`infra/postgres/init`).
- Each service waits for Postgres, **generates JWT keys**, runs
  **makemigrations + migrate**, and starts serving.
- `minio-init` creates the media bucket.
- Workers (outbox→RabbitMQ) and consumers (event handlers) attach; if any starts
  before its tables exist it simply restarts until ready (self-healing).

## 4. See it working

Open **`https://tara.example.com`** → the Tara web app (Arabic RTL / English LTR,
dark/light). Register an account, post, react, comment, add friends, chat in real
time, browse the marketplace, get notifications. The API is at
`https://tara.example.com/api/v1/…`, OpenAPI docs at `/api/v1/docs/`, and the
WebSocket at `wss://tara.example.com/ws/…` — all same-origin through the edge.

## 5. Operations

- **Logs:** Dokploy shows per-container logs. Start with `identity`, then `web`.
- **Self-healing:** containers restart on failure; the nginx edge re-resolves
  backends at request time, so a restarted service is picked up with no reload.
- **Redeploy / update:** push to the branch and redeploy in Dokploy; migrations
  re-run idempotently on boot.
- **Scaling:** raise `--concurrency` on a `*-worker`, or run more `*-consumer`
  replicas (they are competing, idempotent consumers).

## 6. Notes & options

- **Security:** the generated env sets `*_DEBUG=false` and `*_ALLOWED_HOSTS=*`
  (traffic only ever reaches services via the nginx edge). To pass
  `manage.py check --deploy` strictly, pin `*_ALLOWED_HOSTS` to your domain +
  service names. The `tara_common` production-safety check rejects dev-default
  secrets — the generator's random values pass it.
- **Email:** a `mailpit` container catches outbound mail (no real delivery). Swap
  `EMAIL_HOST`/`EMAIL_PORT`/credentials for a real SMTP provider in the env.
- **Search** runs on Postgres (`SEARCH_USE_OPENSEARCH=false`) to keep the
  footprint small; flip it on and add an OpenSearch service for scale.
- **Media uploads (optional):** browser uploads use presigned URLs to MinIO. For
  them to work end-to-end, expose MinIO on its own subdomain (e.g.
  `s3.tara.example.com`) and set `S3_ENDPOINT_URL`/`S3_PUBLIC_BASE` to it (so the
  presigned URL host matches what the browser hits). Everything else works
  without this; it's the one feature that needs the extra hostname.
- **Kubernetes:** for a clustered deployment instead of single-host compose, see
  `infra/k8s/` (Kustomize overlays for all services).
```
