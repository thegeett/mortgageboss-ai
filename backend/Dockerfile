# Backend image (LP-41) — currently used for the Celery worker container in
# docker-compose. The API and worker also run locally via uv; this image lets the
# worker run as a container against the Compose Postgres/Redis (a SEPARATE process
# from the API). Managed with uv.
FROM python:3.12-slim

# uv (pinned image provides the static binaries).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for layer caching (no project, no dev deps).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code, then finish the install.
COPY . .
RUN uv sync --frozen --no-dev

# Default command: run the Celery worker (overridable by the compose service).
CMD ["uv", "run", "celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info"]
