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

From a checkout of this repo:

```bash
./scripts/gen-dokploy-env.sh tara.example.com
```

This writes `.env.dokploy` with a unique strong secret for every service, database,
Redis, RabbitMQ and MinIO. Keep it safe and never commit it. Run it once: new
passwords do not reach an existing database.

**Then fill in the SMTP values** (`EMAIL_HOST`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`). The stack refuses to start without `EMAIL_HOST`, because
new accounts must verify their email before they can sign in. Your provider must
allow sending from `DEFAULT_FROM_EMAIL`.

## 2. Create the Dokploy service

1. Dokploy → **Create Project** → inside it **Create Service → Compose**.
2. **Provider:** point it at this Git repository (and branch).
3. **Compose Path:** `docker-compose.dokploy.yml`.
4. **Environment:** paste the entire generated `.env.dokploy` into the Environment panel.
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
- Each service waits for Postgres, runs the **production safety check**, applies
  its **committed migrations** and starts serving. Identity generates its JWT keys
  and media creates the private bucket.
- Workers (outbox→RabbitMQ) and consumers (event handlers) attach; if any starts
  before its tables exist it simply restarts until ready (self-healing).

## 4. See it working

Open **`https://tara.example.com`**, register, and confirm the verification email
arrives. The API is at `/api/v1/…` and the WebSocket at `wss://tara.example.com/ws/…`,
all through the same origin. Media is served at `/tara-media/…` by presigned URL;
the bucket is private.

The first admin is an account you have registered and verified:

```bash
docker exec tara-identity-1 python manage.py create_admin you@example.com
```

## 5. Operations

- **Logs:** Dokploy shows per-container logs. Start with `identity`, then `web`.
- **Self-healing:** containers restart on failure, and the nginx edge re-resolves
  backends at request time. A RabbitMQ outage pauses event delivery; events wait in
  each service's outbox and flow again when it returns.
- **Update:** push and redeploy. Commit a migration with any model change; services
  apply migrations at boot and never generate them.
- **Scaling:** raise `--concurrency` on a `*-worker` or `WEB_CONCURRENCY`, and adjust
  `mem_limit` to match.
- **Failed events:** a handler that keeps failing is retried over about 40 minutes
  and then dead-lettered. After fixing the cause, put them back with
  `docker exec tara-feed-consumer-1 python manage.py consume_events --replay-dlq`.

### Upgrading an existing deployment

Some releases add required settings. Add them to Dokploy's Environment panel
**before** redeploying, or the stack refuses to start:

| Added in | Variable | Value |
|---|---|---|
| Step 1 wave A | `ADMIN_IDENTITY_SECRET` | `openssl rand -hex 32`, different from `INTERNAL_JWT_SECRET`. Only admin and identity use it. |
| Step 1 wave A | `ADS_SERVE_TOKEN_SECRET` | `openssl rand -hex 32`. Ad tokens issued before the change stop working (they last 30 minutes). |
| Step 1 wave A | `ADS_SERVING_ENABLED` | `false`. Paid ads must not serve until payment verification exists. |

Migrations in that release are additive and run at boot. The search migration
`0004_purge_nonpublic_hashtags` rebuilds hashtag links from public posts in
batches and is safe to re-run.

**Step 1 wave A: deploy post and media together.** Post now asks media to
restrict attachments, and media asks post who may see a restricted image. If
only one of them is updated, posts with photos return 503 until the other
catches up. After both are up, run these one-off commands once, in this order.
Each one is safe to re-run:

```bash
docker exec tara-media-1 python manage.py sanitize_existing_images   # strip EXIF/GPS from old images
docker exec tara-post-1  python manage.py restrict_post_media        # restrict photos of non-public posts
docker exec tara-feed-1  python manage.py relabel_feed_reasons       # friend/follow labels on old feed rows
docker exec tara-search-1 python manage.py reconcile_hashtags        # hashtags only from public posts
```

**Step 1 wave B (comments v2, notifications v2, messenger, marketplace
catalogue, account security).** All new variables are optional:
`GOOGLE_CLIENT_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` and
`TELEGRAM_WEBHOOK_SECRET` (each feature stays off while empty), and
`AUTH_LOGIN_TARGET_RATE` (default `10/min`).

- **Order:** deploy notification, moderation and realtime first. They consume
  the new event types, so they must be running before post, chat, graph and
  marketplace start emitting them.
- **Marketplace:** recreate `marketplace` together with its relay and consumer.
  The old image writes `price=0` with type `fixed`, and the new check
  constraints reject that.
- **Migrations:** chat `0004`, marketplace `0007` and notification `0005` build
  indexes `CONCURRENTLY`, and the first two create the `pg_trgm` extension.
  The database owner can create it, because it is a trusted extension.

After the stack is up, run once:

```bash
docker exec tara-chat-1 python manage.py backfill_message_seq   # read pointers and unread counts for old chats
# Only if Telegram phone verification is configured:
docker exec tara-identity-1 python manage.py set_telegram_webhook --url https://<your-domain>
```

Push subscriptions made before this release have no recorded owner. They are
dropped at the next login, so those users have to turn push on again in Settings.

Add a bucket lifecycle rule that deletes objects under `staging/` after one day.
Uploads now land there first. If an upload is abandoned, its staging object is
never served, but it does take up space.

### Backups

`scripts/backup.sh` saves all databases, media and the JWT keys. Run it daily from
Dokploy's Schedules or cron, and copy the output off the server:

```bash
COMPOSE_PROJECT=tara BACKUP_DIR=/var/backups/tara scripts/backup.sh
```

To restore, start `postgres` and `minio` on empty volumes, run
`scripts/restore.sh <backup directory>`, then start the rest of the stack.

## 6. Notes & options

- **Server size:** the stack uses about 4.6 GB at idle, and the memory limits add up
  to more. Use 12 GB; 8 GB will leave nothing for traffic peaks.
- **Plain HTTP on port 80** redirects to HTTPS through Dokploy's Traefik. If your
  Dokploy uses other entrypoint or cert-resolver names, adjust the `web` labels.
- **Search** runs on Postgres (`SEARCH_USE_OPENSEARCH=false`). Add OpenSearch at scale.
- **MinIO** credentials are the root user, held only by MinIO and the media service.
  Use S3 or Cloudflare R2 instead by setting `S3_ENDPOINT_URL`, keys and
  `S3_PUBLIC_ENDPOINT_URL`.
- **Kubernetes** manifests in `infra/k8s/` have never run on a cluster and need work
  first. See `docs/architecture/project-review-and-plan.md`.
