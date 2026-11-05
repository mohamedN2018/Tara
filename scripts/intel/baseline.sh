#!/usr/bin/env bash
# Tara Intelligence WP 2.0: the baseline run, re-run at the end of every phase.
#
# Runs every backend suite the Intelligence work touches (scripts/test-service.sh,
# in the dev-requirements image) and the web feed specs (vitest), prints one line
# per suite (passed / failed / skipped / wall time) and every failing test id, and
# exits non-zero when a test fails that is not listed in
# scripts/intel/known_failures.txt ("<suite> <test id>  # owner: cause").
#
#   bash scripts/intel/baseline.sh                 # every suite
#   SUITES="feed post" bash scripts/intel/baseline.sh
#
# Needs the core stack (Postgres, Redis) up and each service image built.
set -uo pipefail

cd "$(dirname "$0")/../.."
SUITES="${SUITES:-feed post graph profile marketplace identity moderation media ads web}"
OUT="${BASELINE_OUT:-.intel-baseline}"
KNOWN="scripts/intel/known_failures.txt"
mkdir -p "$OUT"
summary="$OUT/summary.txt"
: > "$summary"
unlisted=0

run_backend() {
  local svc="$1" log="$OUT/$1.log" attempt rc
  for attempt in 1 2 3 4 5 6; do
    bash scripts/test-service.sh "$svc" > "$log" 2>&1
    rc=$?
    # 125: another run holds this suite's env file (or the daemon was busy): wait and retry.
    [ "$rc" -ne 125 ] && break
    sleep 60
  done
  return "$rc"
}

run_web() {
  (cd frontend/web && npx vitest run src/__tests__/feed.spec.ts src/__tests__/homeFeed.spec.ts) \
    > "$OUT/web.log" 2>&1
}

count() {  # count <log> <word>: the number before <word> in vitest's summary line
  grep -Eo "[0-9]+ $2" "$1" | tail -1 | grep -Eo '^[0-9]+' || echo 0
}

progress() {  # progress <log> <chars>: test-service.sh runs pytest -qq (no summary line),
  # so count the outcome characters of its progress lines ("..F.s  [ 42%]").
  grep -E '^[.sFExX]+ *(\[ *[0-9]+%\])?$' "$1" | sed -E 's/ *\[.*$//' | tr -cd "$2" | wc -c | tr -d ' '
}

for svc in $SUITES; do
  start=$(date +%s)
  if [ "$svc" = "web" ]; then run_web; rc=$?; log="$OUT/web.log"; else run_backend "$svc"; rc=$?; log="$OUT/$svc.log"; fi
  secs=$(( $(date +%s) - start ))
  # pytest: "N passed, M failed, K skipped"; vitest: "Tests  N passed (N)".
  if [ "$svc" = "web" ]; then
    passed=$(count "$log" passed); failed=$(count "$log" failed); skipped=$(count "$log" skipped)
    errors=0
  else
    passed=$(progress "$log" '.'); failed=$(progress "$log" 'F'); skipped=$(progress "$log" 'sxX')
    errors=$(progress "$log" 'E')
  fi
  printf '%-12s rc=%-3s passed=%-5s failed=%-3s errors=%-3s skipped=%-3s wall=%ss\n' \
    "$svc" "$rc" "$passed" "$failed" "$errors" "$skipped" "$secs" | tee -a "$summary"
  # Failing ids: pytest's short summary ("FAILED a::b - why" / "ERROR a::b"), vitest's "FAIL file > test".
  grep -E '^(FAILED|ERROR) |^ *FAIL ' "$log" | sed 's/^/    /' | tee -a "$summary"
  while read -r line; do
    id=$(echo "$line" | sed -E 's/^ *(FAILED|ERROR|FAIL) +//; s/ - .*$//')
    if ! grep -qF "$svc $id" "$KNOWN" 2>/dev/null; then
      echo "    UNLISTED: $svc $id" | tee -a "$summary"
      unlisted=$((unlisted + 1))
    fi
  done < <(grep -E '^(FAILED|ERROR) |^ *FAIL ' "$log")
  # A suite that died before any test ran (build error, makemigrations --check) is a failure too.
  if [ "$rc" -ne 0 ] && [ "$failed" = 0 ] && [ "$errors" = 0 ]; then
    if ! grep -qF "$svc <suite>" "$KNOWN" 2>/dev/null; then
      echo "    UNLISTED: $svc <suite> (rc=$rc, see $log)" | tee -a "$summary"
      unlisted=$((unlisted + 1))
    fi
  fi
done

echo "unlisted failures: $unlisted" | tee -a "$summary"
[ "$unlisted" -eq 0 ]
