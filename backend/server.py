"""ASGI entrypoint for serverless hosting (Vercel: see /pyproject.toml [tool.vercel])."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vestnio.api.app import app  # noqa: E402

__all__ = ["app"]
