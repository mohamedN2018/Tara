#!/bin/sh
# One-shot (minio-init container): create the media transcoder's MinIO user,
# scoped to the media bucket's videos/ prefix (roadmap §5.1 "restricted MinIO
# user", 5.2 "a scoped storage user"). Idempotent: re-running updates the
# policy and the secret. The transcoder runs untrusted files through ffmpeg,
# so it never gets the root credentials: it can read the uploads it converts,
# write their renditions and delete the original, and nothing else (no photos,
# no chat files, no other bucket, no admin API).
#
# Env: MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, S3_BUCKET,
#      MEDIA_TRANSCODER_S3_ACCESS_KEY, MEDIA_TRANSCODER_S3_SECRET_KEY,
#      MINIO_URL (default http://minio:9000).
# Skipped when the transcoder keys are empty (external S3/R2: create a scoped
# token there by hand, see docs/deploy/DOKPLOY.md).
set -eu

url="${MINIO_URL:-http://minio:9000}"
bucket="${S3_BUCKET:-tara-media}"
key="${MEDIA_TRANSCODER_S3_ACCESS_KEY:-}"
secret="${MEDIA_TRANSCODER_S3_SECRET_KEY:-}"
export MC_CONFIG_DIR=/tmp/mc

if [ -z "$key" ] || [ -z "$secret" ]; then
  echo "[minio-init] no transcoder keys set; skipping"
  exit 0
fi

tries=0
until mc alias set tara "$url" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo "[minio-init] MinIO did not answer at $url" >&2
    exit 1
  fi
  sleep 2
done

mc mb --ignore-existing "tara/$bucket" >/dev/null

policy=/tmp/tara-transcoder-policy.json
cat > "$policy" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload",
                 "s3:ListMultipartUploadParts"],
      "Resource": ["arn:aws:s3:::$bucket/videos/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::$bucket"],
      "Condition": {"StringLike": {"s3:prefix": ["videos/*"]}}
    }
  ]
}
EOF

mc admin policy create tara tara-transcoder "$policy" >/dev/null
mc admin user add tara "$key" "$secret" >/dev/null
mc admin policy attach tara tara-transcoder --user "$key" >/dev/null 2>&1 || true
echo "[minio-init] transcoder user '$key' limited to $bucket/videos/"
