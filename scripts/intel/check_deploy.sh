#!/usr/bin/env bash
# Tara Intelligence WP 2.4: the feed-signals role in all three setups.
#
#   bash scripts/intel/check_deploy.sh            # static checks + nginx 413 + dev Traefik
#   SKIP_LIVE=1 bash scripts/intel/check_deploy.sh  # static checks and nginx only
#
# 1. Dokploy compose: the re-dumped compose (merge keys expanded, as Dokploy passes
#    it) stays small: base64 size < 100,000 (Dokploy's cap is 131,072).
# 2. Dokploy compose: feed-signals resolves RUN_MIGRATIONS=false; feed keeps true;
#    every other feed container aliases *feed-env.
# 3. nginx edge (frontend/web/nginx.conf): a 100 KB body to /api/v1/feed/signals
#    gets 413; a small one is proxied to tara-feed-signals, /api/v1/feed to tara-feed.
# 4. k8s: the feed overlay builds and routes /api/v1/feed/signals to feed-signals.
# 5. Dev compose (live): Traefik sends /api/v1/feed/signals to feed-signals and
#    /api/v1/feed to feed; feed-signals never ran "[feed] migrate".
set -euo pipefail
cd "$(dirname "$0")/../.."
fail=0
ok() { echo "ok   $*"; }
bad() { echo "FAIL $*"; fail=1; }

# ---- 1 + 2: Dokploy compose ------------------------------------------------------
result=$(node scripts/intel/check_dokploy.cjs || echo '{}')
size=$(echo "$result" | grep -o '"size":[0-9]*' | cut -d: -f2)
if [ -n "$size" ] && [ "$size" -lt 100000 ]; then ok "dokploy compose base64 size $size < 100000"; else bad "dokploy compose size ${size:-?}"; fi
echo "$result" | grep -q '"signals":"false"' && ok "feed-signals RUN_MIGRATIONS=false" || bad "feed-signals RUN_MIGRATIONS"
echo "$result" | grep -q '"feed":"true"' && ok "feed RUN_MIGRATIONS=true" || bad "feed RUN_MIGRATIONS"
echo "$result" | grep -q '"secret":true' && ok "feed-signals has INTEL_SERVE_TOKEN_SECRET" || bad "feed-signals env"
echo "$result" | grep -q '"synthetic":"false"' && ok "production INTEL_ACCEPT_SYNTHETIC=false" || bad "INTEL_ACCEPT_SYNTHETIC"
merged=$(grep -c '<<: \*feed-env' docker-compose.dokploy.yml || true)
[ "$merged" = 1 ] && ok "one merged *feed-env block (feed-signals)" || bad "merged *feed-env blocks: $merged"

# ---- 3: nginx edge -----------------------------------------------------------------
conf="$(pwd -W 2>/dev/null || pwd)/frontend/web/nginx.conf"
name="intel-nginx-check-$$"
if MSYS_NO_PATHCONV=1 docker run -d --rm --name "$name" -p 127.0.0.1:18089:80 \
    -v "$conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.29-alpine > /dev/null; then
  sleep 2
  big=$(head -c 102400 /dev/zero | tr '\0' 'a' | curl -s -o /dev/null -w '%{http_code}' \
    -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:18089/api/v1/feed/signals/)
  [ "$big" = 413 ] && ok "nginx: 100 KB to /api/v1/feed/signals -> 413" || bad "nginx big body -> $big"
  mid=$(head -c 40960 /dev/zero | tr '\0' 'a' | curl -s -o /dev/null -w '%{http_code}' \
    -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:18089/api/v1/feed/signals/)
  [ "$mid" != 413 ] && ok "nginx: 40 KB to /api/v1/feed/signals passes the edge ($mid, no upstream here)" || bad "nginx 40 KB -> 413"
  curl -s -o /dev/null http://127.0.0.1:18089/api/v1/feed/
  logs=$(docker logs "$name" 2>&1)
  echo "$logs" | grep -q 'tara-feed-signals' && ok "nginx: /api/v1/feed/signals -> tara-feed-signals" || bad "nginx signals upstream"
  echo "$logs" | grep -q 'tara-feed could not\|"tara-feed"' && ok "nginx: /api/v1/feed -> tara-feed" || bad "nginx feed upstream"
  docker rm -f "$name" > /dev/null 2>&1 || true
else
  bad "nginx container did not start"
fi

# ---- 4: Kubernetes ---------------------------------------------------------------
if command -v kubectl > /dev/null; then
  k8s=$(kubectl kustomize infra/k8s/overlays/feed 2>/dev/null)
  echo "$k8s" | grep -q 'path: /api/v1/feed/signals' && echo "$k8s" | grep -q 'name: feed-signals' \
    && ok "k8s: /api/v1/feed/signals -> feed-signals" || bad "k8s ingress"
  # Every rendered Deployment runs exactly one container, and every container has an
  # image (an unnamed patch target once appended an image-less "app" container).
  echo "$k8s" | node -e '
    const Y=require("./frontend/web/node_modules/js-yaml");
    const docs=Y.loadAll(require("fs").readFileSync(0,"utf8")).filter(d=>d&&d.kind==="Deployment");
    const bad=docs.filter(d=>{const c=d.spec.template.spec.containers;return c.length!==1||c.some(x=>!x.image)});
    process.exit(docs.length&&!bad.length?0:1);' \
    && ok "k8s: every feed Deployment has one container with an image" || bad "k8s containers"
else
  echo "skip k8s (no kubectl)"
fi

# ---- 5: dev compose (live) -------------------------------------------------------
if [ -z "${SKIP_LIVE:-}" ]; then
  edge="${TARA_EDGE:-http://127.0.0.1:8080}"
  marker="intel-check-$$-$RANDOM"
  curl -s -o /dev/null -X POST "$edge/api/v1/feed/signals/?m=$marker" -H 'Content-Type: application/json' -d '{}'
  curl -s -o /dev/null "$edge/api/v1/feed/?m=$marker"
  sleep 1
  docker logs tara-feed-signals-1 2>&1 | grep -q "signals/?m=$marker" \
    && ok "traefik: /api/v1/feed/signals -> feed-signals" || bad "traefik signals route"
  docker logs tara-feed-1 2>&1 | grep -q "/api/v1/feed/?m=$marker" \
    && ok "traefik: /api/v1/feed -> feed" || bad "traefik feed route"
  docker logs tara-feed-1 2>&1 | grep -q "signals/?m=$marker" && bad "feed served a signals call" || true
  docker logs tara-feed-signals-1 2>&1 | grep -q '\[feed\] migrate' \
    && bad "feed-signals ran migrations" || ok "feed-signals never migrated"
  env=$(docker exec tara-feed-signals-1 printenv RUN_MIGRATIONS 2>/dev/null || echo '?')
  [ "$env" = false ] && ok "feed-signals RUN_MIGRATIONS=$env (dev)" || bad "feed-signals dev env $env"
fi

exit "$fail"
