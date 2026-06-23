"""Block until PostgreSQL accepts connections (used by the container entrypoint)."""

import os
import sys
import time

import psycopg


def main() -> None:
    dsn = (
        f"host={os.getenv('POSTGRES_HOST', '127.0.0.1')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('MARKET_DB_NAME', 'market_db')} "
        f"user={os.getenv('MARKET_DB_USER', 'market')} "
        f"password={os.getenv('MARKET_DB_PASSWORD', 'market-dev-pass')}"
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3):
                print("[marketplace] database is ready")
                return
        except Exception as exc:  # noqa: BLE001
            print(f"[marketplace] waiting for database... ({exc})")
            time.sleep(2)
    print("[marketplace] database did not become ready in time", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
