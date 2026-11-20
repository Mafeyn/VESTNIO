"""Runtime settings, loaded from environment variables (prefix VESTNIO_) or backend/.env."""

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

BACKEND_DIR = Path(__file__).resolve().parent.parent


def normalize_database_url(url: str) -> str:
    """postgres://…?sslmode=require (Neon, Heroku-style) → postgresql+asyncpg://…?ssl=require."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k == "sslmode":
            query.append(("ssl", "require" if v in ("require", "verify-ca", "verify-full") else v))
        elif k in ("channel_binding", "options"):  # libpq-only parameters asyncpg rejects
            continue
        else:
            query.append((k, v))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VESTNIO_", env_file=BACKEND_DIR / ".env", extra="ignore")

    # postgresql+asyncpg://user:password@host:port/dbname — a plain postgres:// URL
    # (as Neon/Vercel give it, incl. ?sslmode=require) is converted automatically.
    database_url: str = Field(
        default="postgresql+asyncpg://vestnio:vestnio@localhost:5432/vestnio",
        validation_alias=AliasChoices("VESTNIO_DATABASE_URL", "DATABASE_URL"),
    )
    # Serverless (Vercel): no pooled connections kept between invocations.
    db_null_pool: bool = Field(default_factory=lambda: bool(os.environ.get("VERCEL")))
    log_level: str = "INFO"

    sources_file: Path = BACKEND_DIR / "sources.yaml"

    # ---- ingestion
    default_poll_minutes: int = 15
    request_timeout_seconds: float = 15.0
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    max_concurrent_fetches: int = 6
    user_agent: str = "VestnioNewsAggregator/1.0 (self-hosted feed reader)"
    respect_robots_txt: bool = True
    guardian_api_key: SecretStr | None = None  # sources needing a missing key are skipped

    # ---- API
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    serve_webapp_dir: Path | None = None  # optional: serve the built Mini App from the API process

    # ---- Telegram (the token never leaves the backend)
    bot_token: SecretStr | None = None
    webapp_url: str | None = None  # public HTTPS URL of the Mini App
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    init_data_max_age_seconds: int = 24 * 3600
    # Webhook mode: Telegram sends this in X-Telegram-Bot-Api-Secret-Token
    webhook_secret: SecretStr | None = None

    @field_validator("database_url", mode="after")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_ids(cls, v):
        if isinstance(v, str):
            return [int(s) for s in v.replace(" ", "").split(",") if s]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
