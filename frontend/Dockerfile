# Frontend image (C1) — Next.js 15 App Router, pnpm, Node 20.
#
# Node 20 matches CI, the only place the version is pinned
# (.github/workflows/frontend-ci.yml:38). pnpm comes from corepack (shipped with Node)
# rather than `npm i -g pnpm`, so the package manager is provisioned the supported way
# and its version is pinned here instead of floating with the registry.
#
# Three stages so the runtime image carries neither the dependency tree nor the build
# toolchain: deps (install) -> builder (compile) -> runner (standalone output only).
#
# ============================================================================
# BUILD-TIME API URL — the single most likely deployment mistake in the C series.
# ============================================================================
# NEXT_PUBLIC_* variables are INLINED INTO THE JAVASCRIPT AT BUILD TIME. They are not
# read at runtime, so setting NEXT_PUBLIC_API_URL in an ECS task definition does
# NOTHING — the value is already compiled into the bundle that shipped.
#
# Both frontend/lib/config.ts:2 and frontend/lib/api/client.ts:5 fall back to
# `http://localhost:8000` when it is unset. So an image built WITHOUT the build arg
# ships a frontend that asks the user's own machine for the API. It fails only in the
# browser, with no server-side error and a green ECS health check.
#
# Therefore, always build with it:
#   docker build --build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai \
#                -t mbai-frontend:staging ./frontend
#
# CHANGING THE API URL REQUIRES A REBUILD, NOT A TASK-DEFINITION EDIT.
#
# Only NEXT_PUBLIC_* values belong here — a build arg is visible in `docker history`,
# so a secret passed this way is a leak, not a shortcut. Verified: NEXT_PUBLIC_API_URL
# is the only non-NODE_ENV environment variable the frontend reads.

# --------------------------------------------------------------------------- #
# Stage 1 — deps: install node_modules from the lockfile only
# --------------------------------------------------------------------------- #
FROM node:20-alpine AS deps
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.33.0 --activate

# Lockfile + manifest only, so this layer caches until dependencies actually change.
COPY package.json pnpm-lock.yaml ./
# --frozen-lockfile: fail rather than silently resolve differently from the committed
# lockfile. A build that quietly drifts from the lockfile is not reproducible.
RUN pnpm install --frozen-lockfile

# --------------------------------------------------------------------------- #
# Stage 2 — builder: compile the app
# --------------------------------------------------------------------------- #
FROM node:20-alpine AS builder
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.33.0 --activate

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# The build-time API URL (see the header). Declared AFTER the source copy so a URL
# change does not invalidate the dependency layers.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Skip Next's anonymous telemetry in CI/containers.
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN pnpm build

# --------------------------------------------------------------------------- #
# Stage 3 — runner: standalone output only
# --------------------------------------------------------------------------- #
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# HOSTNAME=0.0.0.0 is REQUIRED. Next's server binds localhost by default, which is
# reachable only from inside the container — the ALB health check then fails with no
# useful error. Same trap as uvicorn's --host 0.0.0.0.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Non-root. node:alpine already ships a `node` user (uid 1000); reuse it rather than
# minting another.
RUN mkdir -p .next && chown -R node:node /app

# `public/` and `.next/static/` are NOT included in the standalone bundle — Next expects
# them to be copied alongside it. Omitting them yields a server that boots fine and
# serves no CSS, images, or client chunks.
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node

EXPOSE 3000

# server.js is the standalone entrypoint. Plain `node`, not `pnpm start`/`next start` —
# the standalone bundle has no Next CLI and no pnpm.
CMD ["node", "server.js"]
