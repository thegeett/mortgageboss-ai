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

# Worker liveness (C1). A Celery worker has no HTTP endpoint, so without this an
# orchestrator cannot tell "alive" from "alive but not consuming" — a worker that lost
# its broker connection keeps its process up and silently stops processing documents.
# `inspect ping` goes out over the BROKER and back, so it fails exactly in that case.
#
# -d celery@$HOSTNAME pins the probe to THIS container's own node (Docker sets
# HOSTNAME to the container id, and Celery names its node celery@<hostname>), so a
# second healthy worker on the same broker cannot mask this one being dead.
# Shell form, deliberately: $HOSTNAME must expand at runtime, not build time.
#
# NOTE (C1): a HEALTHCHECK is baked into the IMAGE, so it also applies to the API
# container, which runs this same image with a uvicorn command and no Celery node —
# it would report unhealthy forever. Anything running the API from this image MUST
# override the healthcheck: `healthcheck: {test: [...]}` in compose (see
# docker-compose.images.yml), or `healthCheck` in the ECS task definition (C3).
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD uv run celery -A app.tasks.celery_app inspect ping -d celery@$HOSTNAME || exit 1

# Default command: run the Celery worker (overridable by the compose service).
CMD ["uv", "run", "celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info"]
