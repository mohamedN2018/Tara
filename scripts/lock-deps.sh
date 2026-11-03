#!/usr/bin/env bash
# Regenerate exact dependency versions from the images built by `make up`.
# After a dependency change: empty the constraints files, rebuild, then run this.
set -euo pipefail

services="identity profile graph media post feed chat realtime marketplace notification search moderation admin ads"
freeze() { docker run --rm --entrypoint pip "tara/$1:dev" freeze --exclude-editable | grep -vE '^tara[-_]|@ file:'; }

# When services disagree, keep the older version: a package that resolved to it
# has a tighter upper bound than the others (boto3 caps python-dateutil, for one).
oldest() { tr -d '' | sort -Vr | awk -F'==' '{ v[tolower($1)] = $0 } END { for (k in v) print v[k] }' | sort -f; }

for s in $services; do freeze "$s"; done | oldest > constraints.txt
freeze bff | oldest > services/bff/constraints.txt
echo "constraints.txt: $(wc -l < constraints.txt) packages"
