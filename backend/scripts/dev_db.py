"""Start a local PostgreSQL for development without Docker (uses the `pgserver` wheel).

    python scripts/dev_db.py          # start (or reuse) and write VESTNIO_DATABASE_URL into .env
    python scripts/dev_db.py stop

Data lives in <repo>/.pgdata. With Docker available, prefer `docker compose up db`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pgserver

BACKEND = Path(__file__).resolve().parent.parent
PGDATA = BACKEND.parent / ".pgdata"
ENV_FILE = BACKEND / ".env"


def _set_env(key: str, value: str) -> None:
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
    else:
        text = (text.rstrip("\n") + "\n" if text else "") + line + "\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def main() -> None:
    server = pgserver.get_server(PGDATA, cleanup_mode=None)  # keep running after exit
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        server.cleanup()
        print("stopped")
        return
    for db in ("vestnio", "vestnio_test"):
        exists = server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{db}';")
        if "1 row" not in exists:
            server.psql(f"CREATE DATABASE {db};")
    uri = server.get_uri()  # postgresql://postgres:@127.0.0.1:PORT/postgres
    base = uri.rsplit("/", 1)[0].replace("postgresql://", "postgresql+asyncpg://")
    _set_env("VESTNIO_DATABASE_URL", f"{base}/vestnio")
    _set_env("VESTNIO_TEST_DATABASE_URL", f"{base}/vestnio_test")
    print(f"PostgreSQL running: {base}/vestnio  (test db: vestnio_test)")


if __name__ == "__main__":
    main()
