# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

FROM python:3.12-slim

RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --gid 1001 app && \
    mkdir -p /deps && chown app:app /deps

WORKDIR /app

COPY --from=builder --chown=app:app /deps /deps
COPY --chown=app:app . .

ENV PYTHONPATH=/deps:/app \
    PATH=/deps/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000
