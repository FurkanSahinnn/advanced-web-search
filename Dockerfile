# syntax=docker/dockerfile:1

###############################################################################
# Stage 1 — build the React / Vite single-page app.
#
# vite.config.ts emits the bundle to ../backend/advanced_web_search/web, so we
# recreate that directory layout here and copy just the built folder into the
# runtime image. Nothing from Node ends up in the final image.
###############################################################################
FROM node:22-bookworm-slim AS frontend

WORKDIR /app/frontend

# pnpm-lock.yaml is lockfileVersion 9.0 -> pnpm 9. Install deps first so this
# layer is cached as long as the manifest + lockfile are unchanged.
# (frontend/pnpm-workspace.yaml is .dockerignore'd — it is pnpm-10/11-only config
# that pnpm 9 would reject; not needed for the container build.)
RUN npm install -g pnpm@9
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build the SPA. outDir resolves to /app/backend/advanced_web_search/web.
COPY frontend/ ./
RUN pnpm run build


###############################################################################
# Stage 2 — Python runtime. One process serves the JSON/SSE API *and* the SPA.
###############################################################################
FROM python:3.12-slim AS runtime

# System libraries:
#   libgomp1       -> required by onnxruntime (fastembed embeddings + reranker)
#   ca-certificates-> HTTPS to web/academic sources + model downloads
#   curl           -> container HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Bind on all interfaces — the app's 127.0.0.1 default is unreachable from
    # outside the container. (Browse it from the host on the published port.)
    AWSEARCH_HOST=0.0.0.0 \
    AWSEARCH_PORT=8787 \
    # SQLite db, embedding-model cache and HTTP cache live here; mount a volume.
    AWSEARCH_DATA_DIR=/data

WORKDIR /app

# Backend install. Copy only what the package build needs (pyproject reads
# README.md for metadata) so dependency layers cache well.
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
# Drop the SPA built in stage 1 into the package so FastAPI serves it (the app
# locates it at advanced_web_search.__file__/web).
COPY --from=frontend /app/backend/advanced_web_search/web ./backend/advanced_web_search/web
RUN pip install -e .

# Run unprivileged. Pre-create /data owned by the app user so a named volume
# mounted there inherits the correct ownership on first use.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS http://localhost:8787/api/health || exit 1

# --no-browser: there is no browser inside the container.
CMD ["python", "-m", "advanced_web_search", "--no-browser"]
