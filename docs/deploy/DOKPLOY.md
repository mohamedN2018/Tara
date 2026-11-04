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
- `scripts/gen-dokploy-env.sh` — generates `.env_prod` with strong secrets.
- `.env_prod.example` — every production variable, one comment each.

---

## First deploy from zero

The short path from an empty server to a running site. The numbered sections
after this one explain each part in more detail.

**Container names.** Dokploy runs Compose under its own project name (the app
name it shows, for example `tara-web-8kx2qz`), so containers are called
`<prefix>-identity-1`, not `tara-identity-1`. The commands below use `$P`:

```bash
P=$(docker ps --format '{{.Names}}' | sed -n 's/-identity-1$//p' | head -1); echo "$P"
```

### 1. Create the Dokploy compose app

1. Dokploy → **Projects → Create Project** (`tara`) → **Create Service → Compose**.
2. **Provider:** GitHub, repository `mohamedN2018/Tara`, branch
   `feat/web-social-platform` (switch to `main` once it is merged).
3. **Compose type:** Docker Compose. **Compose path:** `./docker-compose.dokploy.yml`.
4. Leave **Isolated deployment** off: the compose file already joins
   `dokploy-network`, which Traefik routes through.

### 2. Paste the environment

1. Generate the file once, on any machine with bash and openssl (Git Bash works):

   ```bash
   ./scripts/gen-dokploy-env.sh tara.yourdomain.com   # writes .env_prod; --force overwrites
   ```

   It refuses to overwrite an existing `.env_prod`. The file is git-ignored.
2. Fill the `# === OWNER MUST FILL ===` block at its top: `DOMAIN`,
   `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
   (empty means `no-reply@DOMAIN`), `LIVEKIT_NODE_IP` and `LIVEKIT_TURN_DOMAIN`.
   S3/R2, Google and Telegram are optional. The stack refuses to start while
   `DOMAIN` or `EMAIL_HOST` is empty.
3. Dokploy → the compose service → **Environment** → paste the whole file → **Save**.
4. Keep a copy in a password manager. Do not regenerate it after the first
   deploy: new database passwords never reach an existing volume, and a new
   JWT key signs everyone out.

Everything else is already production-safe: `DEBUG=false` everywhere, the
production rate limits, ads serving off, moderation on, and allowed hosts and
CORS pinned to `DOMAIN`. Identity sets secure cookies and HSTS when DEBUG is
off, and the nginx edge sends HSTS and the CSP for every response.

### 3. Domains and Cloudflare DNS

- **A `*.deplois.net` subdomain:** set `DOMAIN=tara.deplois.net` (or similar)
  and make sure its DNS points at this server. Nothing else to do.
- **Your own domain behind Cloudflare:**
  1. Add an `A` record `tara` → server IP as **DNS only** (grey cloud) and
     deploy, so Let's Encrypt can issue the certificate.
  2. Then switch it to **Proxied** (orange cloud) and set SSL/TLS to
     **Full (strict)**. WebSockets (`/ws/`, `/rtc`) work through the proxy.
  3. Cloudflare cannot proxy UDP. Add a second record such as `turn` → server
     IP as **DNS only**, and set `LIVEKIT_TURN_DOMAIN=turn.yourdomain.com` and
     `LIVEKIT_NODE_IP=<server public IP>`. Otherwise calls connect but carry no media.
  4. The free plan caps request bodies at 100 MB, so larger video uploads fail
     through the proxy.
- Leave Dokploy's **Domains** tab empty. The `web` service already carries the
  Traefik labels for `Host(${DOMAIN})` with the `letsencrypt` resolver.

Then press **Deploy**. Every web container waits for Postgres, runs
`manage.py check --deploy --fail-level ERROR`, and applies its migrations
(`RUN_MIGRATIONS=true`). Workers and consumers never migrate. There is no
separate migrate job to run.

### 4. Volumes and backups

Named volumes, prefixed with `$P`: `pgdata`, `redisdata`, `rabbitmqdata`,
`miniodata` and `identity-keys`. Only Postgres, MinIO and the JWT keys need
backups. Redis is a cache, and RabbitMQ is refilled from each service's outbox.
With `.env_prod` the JWT keys come from the environment, so `identity-keys`
stays empty.

Schedule a daily backup (Dokploy **Schedules** or cron on the host). Dokploy
clones the repo under `/etc/dokploy/compose/<app>/code`:

```bash
COMPOSE_PROJECT=$P BACKUP_DIR=/var/backups/tara /etc/dokploy/compose/<app>/code/scripts/backup.sh
```

Copy `/var/backups/tara` off the server, and keep `.env_prod` with it: the
dump has no way to log in without those passwords. To restore, see
[Backups](#backups).

### 5. LiveKit UDP ports and TURN

Calls start because `.env_prod` sets `COMPOSE_PROFILES=calls` and generates the
LiveKit key and secret. Open these on the host firewall or cloud security group:

```bash
ufw allow 7881/tcp && ufw allow 50000/udp && ufw allow 3478/udp
```

Set `LIVEKIT_NODE_IP` to the server's public IPv4 (required behind Cloudflare,
recommended everywhere). To deploy without calls, remove `calls` from
`COMPOSE_PROFILES` and empty `LIVEKIT_API_KEY`. Details: [Calls (LiveKit)](#7-calls-livekit).

### 6. Create the first admin

Register on the site, open the verification email, then:

```bash
docker exec $P-identity-1 python manage.py create_admin you@example.com
```

Sign out and back in: the admin role arrives with the next token.

### 7. Post-deploy checks

```bash
curl -fsS https://$DOMAIN/healthz.txt                      # "ok" from the edge
curl -fsS https://$DOMAIN/.well-known/jwks.json             # identity's public key
docker ps --filter "name=$P-" --format '{{.Names}} {{.Status}}' | grep -v healthy   # only workers/consumers (no healthcheck)
docker exec $P-feed-consumer-1 python -m tara_events.topology migrate  # once: sets the tara-dlq-* policies
docker exec $P-feed-consumer-1 python -m tara_events.topology status   # then exit 0
docker exec $P-identity-1 python manage.py check --deploy             # warnings only, no errors
```

Then in a browser: register and receive the email, post a photo, send a chat
message (WebSocket), and open **Admin → Health**: every service `ready`.

On a fresh install the only one-off command is that single `topology migrate`.
Queue arguments already route dead letters, but `topology status` reports
`policy ... not applied` (exit 1) until the policies exist. `backfill_search`,
`backfill_message_seq` and the wave A commands only convert data from older
releases. Running them on a fresh install is harmless.

### 8. Upgrading and rolling back

**Upgrade.**
1. Read the [upgrade notes](#upgrading-an-existing-deployment) for every release
   since yours, and add any new variables to the Environment tab first.
2. Run `scripts/backup.sh`.
3. Push or merge to the deployed branch and press **Deploy** (or turn on
   Dokploy's auto-deploy webhook). Migrations apply at boot.
4. Run that release's one-off commands, each safe to re-run:

| Release | Command |
|---|---|
| 1.0c DLQ topology | `docker exec $P-feed-consumer-1 python -m tara_events.topology migrate --dry-run`, then without `--dry-run` ([details](#upgrading-dlq-topology)) |
| Search v2 (1.15) | `docker exec $P-search-consumer-1 python manage.py backfill_search` |
| Wave B messenger | `docker exec $P-chat-1 python manage.py backfill_message_seq` |
| Any | `docker exec $P-identity-1 python manage.py create_admin <email>` |

**Roll back.** Point the service at the previous commit (a tag, or revert on
the branch) and redeploy. Migrations are additive, so the previous image runs
on the newer schema. Do not migrate backwards. If data really has to go back,
restore the backup taken in step 2. The DLQ change has its own
`python -m tara_events.topology rollback`.

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

This writes `.env_prod` (git-ignored) with a unique strong secret for every
service, database, Redis, RabbitMQ, MinIO, the JWT RS256 pair, VAPID and
LiveKit. It refuses to overwrite an existing file unless you pass `--force`.
Keep it safe and never commit it. Run it once: new passwords do not reach an
existing database. Deployments generated before 2026-11-04 have a
`.env.dokploy` instead, which keeps working.

**Then fill in the `OWNER MUST FILL` block** (domain, SMTP, LiveKit IP). The
stack refuses to start without `EMAIL_HOST`, because new accounts must verify
their email before they can sign in. Your provider must allow sending from
`DEFAULT_FROM_EMAIL`.

## 2. Create the Dokploy service

1. Dokploy → **Create Project** → inside it **Create Service → Compose**.
2. **Provider:** point it at this Git repository (and branch).
3. **Compose Path:** `docker-compose.dokploy.yml`.
4. **Environment:** paste the entire generated `.env_prod` into the Environment panel.
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
docker exec $P-identity-1 python manage.py create_admin you@example.com   # $P: see "Container names"
```

The `tara-…-1` names in the notes below assume project `tara`. On Dokploy,
replace `tara` with `$P`.

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
`AUTH_LOGIN_TARGET_RATE` (default `10/min`), and `POST_REPORT_RATE` (post and
comment reports per user, default `20/hour`).

- **Order:** deploy notification, moderation and realtime first. They consume
  the new event types, so they must be running before post, chat, graph and
  marketplace start emitting them.
- **Marketplace:** recreate `marketplace` together with its relay and consumer.
  The old image writes `price=0` with type `fixed`, and the new check
  constraints reject that.
- **Migrations:** chat `0004`, marketplace `0007` and notification `0005` and
  `0006` build indexes `CONCURRENTLY`, and the first two create the `pg_trgm`
  extension. The database owner can create it, because it is a trusted
  extension. Feed `0003` adds a small `post_state` table.
- **Hardening pass (same release):**
  - Realtime starts Daphne with 64 KiB WebSocket frame and message limits.
  - The SPA sends the realtime token as the WebSocket subprotocol, so deploy
    realtime before the frontend. Realtime still accepts `?token=` for SPAs
    cached from before the change.
  - Media now accepts HEIC (`pillow-heif`) and runs `media.expire_stale_uploads`
    every 15 minutes from the beat embedded in its relay worker (`-B`). It
    also adds the `staging/` lifecycle rule below to the bucket by itself.
  - New optional variables, all with safe defaults:
    `TARA_IDEMPOTENCY_STALE_SECONDS` (60), `TARA_JWKS_TIMEOUT` (5),
    `ADMIN_HEALTH_SNAPSHOTS_KEPT` (500), `PRESENCE_BLOCK_MEMORY_TTL` (3600),
    `MARKETPLACE_REVIEW_MIN_INQUIRY_AGE_SECONDS` (86400) and
    `MARKETPLACE_REVIEW_SELLER_WINDOW_DAYS` (30).

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

**Step 1 events (1.13 backend, 1.14 web).**

- **New variables:** none. **New containers:** none. The post worker's
  embedded beat gains `gatherings.tick` (every 5 minutes: reminders about
  24 h and 1 h before an event, once each, and marking ended events).
- **Order (roadmap 3.3, new event types):** deploy moderation and
  notification first, so their queues bind `gathering.reported` and the
  `gathering.*` notification events before post emits them. There is no
  alternate exchange yet (1.0g), so an event published before those queues
  are bound is dropped: on a fresh single deploy nothing is lost (no events
  exist yet), but on an existing install deploy the consumers first.
- **Migrations (additive, run at boot):** post `gatherings 0001_initial`.
- **Edge:** `/api/v1/events` is routed to post (nginx in `frontend/web/nginx.conf`,
  and the Traefik labels in `infra/compose/docker-compose.yml`).
- **Recreate together:** `post`, `post-worker`, `post-consumer`, `moderation`,
  `moderation-consumer`, `notification`, `notification-consumer` and `web`.

**Step 8 foundations (8.1 audit, 8.11 monitoring, 8.12 capabilities).**

- **New containers:** `admin-worker` (Celery with embedded beat: outbox relay,
  health poll every 30 s, platform statistics every 5 min; 256 MB) and
  `admin-consumer` (the unified audit log; 192 MB). Keep `admin-worker` at
  one replica, because beat is embedded.
- **New variables, all optional:** `IDENTITY_EMIT_AUDIT_EVENTS` and
  `MODERATION_EMIT_AUDIT_EVENTS` (default `true`), and on admin
  `ADMIN_HEALTH_POLL_SECONDS` (30), `ADMIN_STATS_POLL_SECONDS` (300),
  `ADMIN_STATS_TIMEOUT` (5), `ADMIN_AUDIT_EXPORT_MAX_ROWS` (10000),
  `ADMIN_AUDIT_EXPORT_RATE` (`10/min`) and `ADMIN_BFF_READY_URL`.
- **Order (roadmap 3.3, new event types):** on an existing install, deploy
  this release with both `*_EMIT_AUDIT_EVENTS=false`, so `admin-consumer`
  declares its `admin.events` queue before anything emits, then set them to
  `true` and redeploy identity and moderation. On a fresh install leave them on.
- **Migrations (additive, run at boot):** identity `0004_rolecapability`,
  admin `0003` (audit entries, statistics, outbox) and `0004`, which copies the
  old admin audit rows into the new log once.
- **Tokens:** access tokens now carry a sorted `caps` claim and no longer carry
  the email. Tokens issued before the deploy still work for up to 15 minutes:
  services derive their capabilities from their roles.
- **Edge:** nginx now sets `X-Request-Id` itself and drops a client's
  `X-Geo-Region`, so a client cannot choose what reaches the audit log.

### Upgrading: DLQ topology

Roadmap 1.0c. Before this release every `<service>.events.dlq` was bound to
`tara.events.dlx` with `#`, so each DLQ received every service's dead letters.
Now each DLQ is bound with its own queue name, and each queue dead-letters with
its own name as routing key: the queue argument `x-dead-letter-routing-key` on
fresh installs, and a policy `tara-dlq-<queue>` on queues that already exist.
RabbitMQ refuses to redeclare an existing queue with a new argument (406), so the
consumers keep the old arguments, log `keeps its pre-1.0c arguments`, and get the
routing key from the policy. Retry queues do not change.

The tool is `python -m tara_events.topology` and runs in any service
container. It uses `RABBITMQ_URL` and the management API at
`http://rabbitmq:15672` (set `RABBITMQ_MANAGEMENT_URL` to override it).
Every command is safe to re-run.

A fresh install routes correctly without it, but run `migrate` once anyway: the
policies repeat what the queue arguments already say, and without them
`topology status` reports `policy ... not applied` and exits 1.

1. **Deploy the release.** All consumers restart as usual. Nothing changes in
   routing yet, because the old `#` bindings are still there. `--replay-dlq`
   now replays only its own service's dead letters, and leaves other services'
   copies for step 4.
2. **Back up the broker definitions:**

   ```bash
   docker exec tara-rabbitmq-1 rabbitmqctl export_definitions /tmp/defs-before-1.0c.json
   docker cp tara-rabbitmq-1:/tmp/defs-before-1.0c.json /var/backups/tara/
   ```

3. **Dry run.** It changes nothing, and it lists the bindings, policies and
   unbinds it would make, with a per-DLQ table (`before`, `kept`, `moved_out`,
   `moved_in`, `dropped`, `after`):

   ```bash
   docker exec tara-feed-consumer-1 python -m tara_events.topology migrate --dry-run
   ```

4. **Apply** at a quiet hour. It takes seconds. The order matters, and the tool
   follows it:
   1. It binds each DLQ with its queue name.
   2. It sets the policies and waits until RabbitMQ reports them applied. If a
      policy is shadowed, it stops here with nothing unbound.
   3. It removes the `#` bindings.
   4. It sorts the messages already in the DLQs by the origin queue in
      `x-death`. A service's own messages stay. A foreign copy whose origin DLQ
      already holds the same event is a duplicate of the old fan-out and is
      dropped. Any other foreign copy moves to its origin's DLQ (publisher
      confirm first, then ack) and gets the `x-tara-origin-queue` header.
      Messages with no known origin stay where they are. Pass
      `--keep-duplicates` to move duplicates instead of dropping them.

   ```bash
   docker exec tara-feed-consumer-1 python -m tara_events.topology migrate
   ```

   It exits 1 and prints `PROBLEM:` when a count does not add up, for example
   when dead letters arrived during the run. Re-run it in that case.
5. **Verify:**

   ```bash
   docker exec tara-feed-consumer-1 python -m tara_events.topology status   # exit 0: every DLQ bound only to its own queue, every policy applied
   docker exec tara-feed-consumer-1 python -m tara_events.topology migrate  # a second run: "no topology changes needed", 0 moved, 0 dropped
   ```

   On the broker, `rabbitmqctl list_policies` shows one `tara-dlq-*` policy
   per queue, and `rabbitmqctl list_bindings source_name destination_name routing_key | grep dlx`
   shows no `#` binding.
6. **Rollback** (the same container, any time):

   ```bash
   docker exec tara-feed-consumer-1 python -m tara_events.topology rollback
   ```

   It re-adds `#` first and only then deletes the policies, so no dead letter
   is ever left without a matching binding. Messages that were moved stay in
   their origin's DLQ, where they belong either way. The previous image also
   works against both topologies, so the code can be rolled back
   independently. `rabbitmqctl import_definitions` only adds objects and does
   not remove the policies, so use `rollback` rather than the backup to undo
   the change.

**Policies do not merge.** Only the highest-priority policy that matches a queue
applies. The `tara-dlq-*` policies have priority 10 and match one queue each.
A later queue policy on `*.events` (for example a length limit) must either
include `dead-letter-exchange` and `dead-letter-routing-key`, or have a lower
priority. Otherwise dead letters go back to the event routing key, which no
DLQ is bound to any more, and they are dropped. `topology status` reports a
shadowed policy. The 1.0g alternate-exchange policy applies to exchanges, so
it does not conflict.

### Upgrading: user management console (8.6) and suspensions (8.4)

- **Migrations (additive, run at boot):** identity `0005_account_suspension`
  (a new table) and admin `0005_auditentry_reason` (a column with a constant
  default, no rewrite).
- **New variables, all optional:** on identity
  `IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS` (default `true`) and
  `IDENTITY_SUSPENSION_EXPIRY_SECONDS` (60, how often `identity-beat` lifts
  suspensions past their end date); on admin `PROFILE_INTERNAL_URL`
  (`http://profile:8000`), `ADMIN_USERS_CALL_TIMEOUT` (3) and
  `ADMIN_USER_REVEAL_RATE` (`30/hour` per staff member).
- **Order (new event types):** on an existing install deploy once with
  `IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS=false`, so `admin-consumer` binds
  `account.suspended`, `account.unsuspended`, `account.signed_out` and
  `account.verification.resent` first, then set it to `true` and redeploy
  identity. With the flag off, suspensions still revoke sessions; only the
  events (and so their audit rows) are missing.
- **Services:** profile (`/internal/v1/profiles/search/`, `by-account/`),
  post, marketplace and moderation (`/internal/v1/stats/accounts/<id>/`) gain
  internal read endpoints. Until they are redeployed, the console's handle and
  name search answers 503 and the per-account counts show as unavailable.
- **No new containers, no one-off commands.**

### Upgrading: search v2 (1.15)

- **Migrations (search, run at boot):** `0005_search_v2` (new columns with
  `db_default`, so the old indexer can keep writing, plus two new tables),
  `0006_renormalize_documents` (fills the normalised columns in committed
  batches) and `0007_search_v2_indexes` (`pg_trgm`, then the trigram and
  recent-sort indexes built `CONCURRENTLY`). No other service migrates.
- **New variables, all optional:** on profile `PROFILE_EMIT_PAGE_UPDATED`
  (default `true`); on search `POST_INTERNAL_URL`, `PROFILE_INTERNAL_URL`,
  `MARKETPLACE_INTERNAL_URL` (the service names on port 8000) and
  `SEARCH_INTERNAL_TIMEOUT` (1.5 s). Search already gets `GRAPH_INTERNAL_URL`.
- **Order (one new event type, `page.updated`):** on an existing install deploy
  once with `PROFILE_EMIT_PAGE_UPDATED=false`, so `search-consumer` binds
  `page.updated`, `group.*`, `gathering.*` and `listing.created`/`updated`
  first; then set it to `true` and redeploy profile. Every other change is an
  additive payload field.
- **Services:** graph gains `POST /internal/v1/relationships/batch/`; post gains
  `/internal/v1/search/gatherings/<id>/` and the export endpoints; profile and
  marketplace gain export endpoints. Until graph is redeployed, people and page
  results come back without the relationship, mutual-friend and follower data.
- **One-off command, after all services run the new code:**

  ```bash
  docker exec tara-search-consumer-1 python manage.py backfill_search
  ```

  It indexes existing people, pages, groups, public posts, public events and
  active listings from the owners' export endpoints, and is safe to re-run.
- **No new containers.**

### Upgrading: groups (1.11, 1.12)

- **Migrations (additive, run at boot):** profile `groups 0001_initial` (new
  tables); post `0007_group_posts_and_readmodels` (nullable `group_id`,
  `pinned_at`, `approval_state` with a constant default, and the new read-model
  tables), then `0008_post_group_idx` (the group feed index, built
  `CONCURRENTLY`, outside a transaction); gatherings `0002_group_id`.
- **New variables, all optional:** on profile `GROUP_REPORT_RATE` (group reports
  per account, default `20/hour`) and `PROFILE_EMIT_GROUP_EVENTS` (default
  `true`); on post `POST_EMIT_GROUP_EVENTS` (default `true`). Post already gets
  `PROFILE_INTERNAL_URL`.
- **Order (new event types):** on an existing install deploy once with
  `PROFILE_EMIT_GROUP_EVENTS=false` and `POST_EMIT_GROUP_EVENTS=false`, so
  `post-consumer`, `notification-consumer`, `moderation-consumer` and
  `search-consumer` bind `group.*` first; then set both to `true` and redeploy
  profile and post. With the flags off, groups still work: post answers every
  group check from profile's internal access endpoint instead of its read model,
  and no group notifications are sent.
- **Edge:** `/api/v1/groups` is routed to profile in `frontend/web/nginx.conf`
  and in the Traefik labels; redeploy `web` with the new SPA.
- **No new containers, no one-off commands** (there are no groups to backfill).

### Upgrading: Dokploy env and compose parity (7.13)

- **No new containers, no migrations, no one-off commands.** An existing
  `.env.dokploy` keeps working unchanged.
- **Now wired (they were generated but never reached the containers):**
  `PROFILE_EMIT_GROUP_EVENTS`, `POST_EMIT_GROUP_EVENTS`, `GROUP_REPORT_RATE`
  and `POST_REPORT_RATE`. The groups two-step upgrade only takes effect from
  this release.
- **New optional variables, production defaults:** the auth throttles
  (`AUTH_REGISTER_RATE`, `AUTH_LOGIN_RATE`, `AUTH_PASSWORD_RATE`),
  `TARA_READ_RATE`/`TARA_WRITE_RATE`, `MODERATION_REPORT_RATE`, the admin,
  calls, marketplace, search and presence knobs listed in `.env_prod.example`,
  and `LEGAL_TERMS_VERSION`, `LEGAL_PRIVACY_VERSION`, `REGISTRATION_MIN_AGE`,
  `PROFILE_HANDLE_CHECK_RATE` and `PROFILE_CALL_TIMEOUT` for registration
  (track 1D). Bump the legal versions together with `frontend/web/src/lib/legal.ts`.
- **Defaults derived from `DOMAIN`:** each `<SERVICE>_ALLOWED_HOSTS`, each
  `<SERVICE>_CORS_ORIGINS`, `LIVEKIT_URL`, `VAPID_SUBJECT` and
  `DEFAULT_FROM_EMAIL`. Values already in the Environment tab still win.
- **Admin health:** the stack sets `ADMIN_BFF_READY_URL` empty, so the console
  stops polling the dev-only BFF and stops reporting `degraded` because of it.
- **Postgres** gets the database settings through `environment` instead of
  `env_file: .env`. The init script only runs on an empty volume, so an
  existing database is not touched.
- **S3/R2** now works as documented: `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID` and
  `S3_SECRET_ACCESS_KEY` override the bundled MinIO.
- **JWT keys from the environment:** `.env_prod` carries
  `IDENTITY_JWT_PRIVATE_KEY`/`IDENTITY_JWT_PUBLIC_KEY`. On an existing install,
  do not add a new pair, because that signs everyone out. Leave them unset (the
  `identity-keys` volume keeps signing), or copy the volume's two PEM files
  into them as one line with literal `\n`.

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

## 7. Calls (LiveKit)

Voice and video calls (roadmap 3.7, 3.8) run on a `livekit` container
(`livekit/livekit-server:v1.13.10`, config in `infra/livekit/livekit.yaml`, 512 MB).
It starts only with `COMPOSE_PROFILES=calls`. Chat turns calls on only when
`LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` are both set. With either one empty,
every call endpoint answers `503 calls_unavailable` and the SPA hides its call
buttons. `scripts/gen-dokploy-env.sh` generates the key and secret and sets the
profile.

**Variables** (names only, values in Dokploy). `LIVEKIT_API_KEY` and
`LIVEKIT_API_SECRET` go to chat and livekit; the secret must be at least 32
characters, and it signs join tokens and webhooks. `LIVEKIT_URL`
(`wss://<domain>`) is what browsers connect to. `LIVEKIT_INTERNAL_URL`
(`http://livekit:7880`) is what chat uses to kick participants and close rooms.
The livekit container also reads `LIVEKIT_NODE_IP`, the server's public IP; if
it is empty, LiveKit finds the IP over STUN at boot. It reads
`LIVEKIT_TURN_DOMAIN` (default `DOMAIN`) and `LIVEKIT_TURN_ENABLED` (default
`true`) as well. Optional chat settings, with their defaults:

| Variable | Default |
|---|---|
| `CALL_RING_TIMEOUT_SECONDS` | 45 |
| `CALL_TOKEN_TTL_SECONDS` | 600 (capped at 600) |
| `CALL_MAX_PARTICIPANTS` | 16 |
| `CALL_RECONCILE_AFTER_SECONDS` | 120 |
| `CALL_START_RATE` | `20/min` |
| `LIVEKIT_API_TIMEOUT` | 3 |

**Ports.** Signalling uses no extra port: the `web` edge proxies `/rtc`
(WebSocket) to `livekit:7880`, behind the same TLS as the site. Media goes
straight to the host, so open these in the host firewall or cloud security group:

| Port | Use |
|---|---|
| UDP 50000 | RTC media; every session is multiplexed on this one port |
| TCP 7881 | RTC over TCP, the fallback when UDP is blocked |
| UDP 3478 | TURN/UDP, a relay for clients behind strict NATs |

**TURN.** LiveKit's built-in TURN server listens on UDP 3478 with
`turn.domain = LIVEKIT_TURN_DOMAIN`. Join tokens give clients its address, so
no TURN credentials ship in the bundle. The relay range (30000 to 40000) only
carries traffic between the TURN server and the SFU inside the container, so
you do not open it. TURN over TLS on 443 is deferred, because Traefik owns 443.
Behind a strict NAT, with UDP 3478 blocked as well, signalling still connects
but media does not. Test once from a phone on mobile data (roadmap 3.7).

**Webhook.** LiveKit posts room events to
`http://chat:8000/internal/v1/livekit/webhook/` on the internal network. The
edge never routes `/internal/`, and chat checks the webhook's signature against
the raw body (the official SDK's `WebhookReceiver`). Both gates apply. If an
edge route to `/internal/` were ever added, the signature would still reject
forged calls.

**Upgrading an existing install.** The call events (`call.started`,
`call.answered`, `call.declined`, `call.ended` and `call.missed`) are new
(roadmap 3.3). Deploy this release once with `LIVEKIT_API_KEY` and
`LIVEKIT_API_SECRET` empty, so that realtime-bridge and notification-consumer
declare their bindings before anything emits. Then set the variables, add
`calls` to `COMPOSE_PROFILES` and redeploy. Chat migration `calls/0001` is
additive. The chat worker's beat runs `calls.sweep` every 5 s (unanswered calls
become missed after 45 s) and `calls.reconcile` every 60 s (it asks LiveKit
about quiet active calls).

**Check it works:**
1. `GET /api/v1/calls/config/` returns `enabled: true`.
2. Start a call between two accounts. The browser opens a WebSocket to
   `wss://<domain>/rtc`.
3. If signalling connects but there is no audio, the media ports are closed.
