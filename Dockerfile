# -----------------------------------------------------------------------------
# Stage 1: Build the React 19 Operator Workbench UI
# -----------------------------------------------------------------------------
FROM node:22-alpine AS ui-builder
WORKDIR /app/web

# Install web dependencies
COPY web/package.json web/package-lock.json* ./
RUN npm install

# Build static assets
COPY web/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Runtime image with Python and Beancount dependencies
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runner
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn==0.52.4 \
    ofxtools==1.1.1 \
    beancount==3.2.3

# Copy application source
COPY src/ /app/src/
RUN pip install --no-cache-dir -e .

# Copy built frontend from ui-builder
COPY --from=ui-builder /app/web/dist /app/web/dist

# Expose default port
EXPOSE 8000

# Volume mount point for data persistence
VOLUME ["/data"]

# Default entrypoint runs ironledger web pointing to persistent /data directory
CMD ["python", "-m", "ironledger.cli", "web", "--db", "/data/ironledger.db", "--projection-db", "/data/projection.db", "--host", "0.0.0.0", "--port", "8000"]
