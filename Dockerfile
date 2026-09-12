# IronLedger Multi-Stage Non-Root Distroless/Slim Production Image
# Syntax: docker/dockerfile:1

# Stage 1: Build & Dependency Wheel Cache
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip wheel --no-cache-dir --wheel-dir /build/wheels -e .

# Stage 2: Minimal Distroless / Hardened Runtime
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="IronLedger Enterprise Node"
LABEL org.opencontainers.image.description="Local-first Enterprise Financial Ingestion & Accounting Engine"
LABEL org.opencontainers.image.vendor="IronLedger Infrastructure"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Hardened Non-Root Service Identity (UID 10001, GID 10001)
RUN groupadd -g 10001 ironledger \
    && useradd -u 10001 -g ironledger -s /bin/false -M -d /app ironledger \
    && mkdir -p /app/data /app/.ironledger /app/config \
    && chown -R ironledger:ironledger /app

COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

COPY --chown=ironledger:ironledger src/ /app/src/
COPY --chown=ironledger:ironledger deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER 10001:10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IRONLEDGER_DB_PATH=/app/data/ironledger.db \
    IRONLEDGER_PROJECTION_DB_PATH=/app/data/projection.db \
    IRONLEDGER_CONFIG_DIR=/app/config

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "ironledger.web.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
