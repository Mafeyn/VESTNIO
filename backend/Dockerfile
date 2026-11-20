# One image for api, worker, bot and migrations (different commands in compose).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini sources.yaml ./
COPY migrations ./migrations
COPY vestnio ./vestnio

RUN useradd --system --uid 10001 vestnio
USER vestnio

EXPOSE 8000
CMD ["uvicorn", "vestnio.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
