"""Block until PostgreSQL accepts connections (used by the container entrypoint)."""

import os
import sys
import time

import psycopg


def main() -> None:
    dsn = (
        f"host={os.getenv('POSTGRES_HOST', '127.0.0.1')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('MEDIA_DB_NAME', 'media_db')} "
        f"user={os.getenv('MEDIA_DB_USER', 'media')} "
        f"password={os.getenv('MEDIA_DB_PASSWORD', 'media-dev-pass')}"
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3):
                print("[media] database is ready")
                return
        except Exception as exc:  # noqa: BLE001
            print(f"[media] waiting for database... ({exc})")
            time.sleep(2)
    print("[media] database did not become ready in time", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
