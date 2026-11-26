# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev libc6-dev && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

FROM python:3.12-slim

# Install git required by Advanced Mode versioning & branch workflows
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy static standalone Docker CLI binary (Phase 5 Decision 12 - DooD Policy)
COPY --from=docker:27.5.1-cli /usr/local/bin/docker /usr/local/bin/docker

RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --gid 1001 app && \
    mkdir -p /deps && chown app:app /deps

WORKDIR /app

COPY --from=builder --chown=app:app /deps /deps
COPY --chown=app:app . .

ENV PYTHONPATH=/deps:/app \
    PATH=/deps/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin \
    PYTHONUNBUFFERED=1 \
    ONX_DEPLOYMENT_PROFILE=vps \
    ONX_PANEL_BIND_HOST=0.0.0.0 \
    ONX_PANEL_BIND_PORT=8000 \
    ONX_DATABASE_URL=sqlite+aiosqlite:////app/data/onx.db

# Create data dirs with correct ownership before switching to non-root
USER root
RUN mkdir -p /app/data/servers /app/data/backups /app/data/host-state /app/config && \
    chown -R app:app /app/data /app/config
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

# Use a shell wrapper so alembic runs before uvicorn starts
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
