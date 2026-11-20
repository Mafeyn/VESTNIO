"""Shared fixtures.

Database tests run against a real PostgreSQL given by VESTNIO_TEST_DATABASE_URL
(env var or backend/.env). `python scripts/dev_db.py` sets one up locally; in Docker
use the compose `db` service. Without it, DB-backed tests are skipped.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from vestnio.config import Settings, get_settings

BACKEND = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def _test_db_url() -> str | None:
    if os.environ.get("VESTNIO_TEST_DATABASE_URL"):
        return os.environ["VESTNIO_TEST_DATABASE_URL"]
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("VESTNIO_TEST_DATABASE_URL="):
                return line.split("=", 1)[1].strip() or None
    return None


TEST_DB_URL = _test_db_url()
requires_db = pytest.mark.skipif(not TEST_DB_URL, reason="VESTNIO_TEST_DATABASE_URL not configured")


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=TEST_DB_URL or "postgresql+asyncpg://invalid/none",
        max_retries=2,
        backoff_base_seconds=0.01,
        request_timeout_seconds=2,
        sources_file=tmp_path / "sources.yaml",
    )


@pytest.fixture(scope="session")
def migrated_db():
    """Run the real Alembic migrations once (down to base, then up to head)."""
    if not TEST_DB_URL:
        pytest.skip("VESTNIO_TEST_DATABASE_URL not configured")
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-x", f"url={TEST_DB_URL}", *args],
            cwd=BACKEND,
            check=True,
            capture_output=True,
        )
    return TEST_DB_URL


@pytest.fixture
async def sessionmaker(migrated_db):
    from vestnio.db import dispose_engine, get_sessionmaker, init_engine

    init_engine(migrated_db, null_pool=True)
    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(text("TRUNCATE articles, ingestion_runs, sources RESTART IDENTITY CASCADE"))
        await s.commit()
    yield sm
    await dispose_engine()


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
