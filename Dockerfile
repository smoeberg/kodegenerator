# Multi-stage Dockerfile for Digital Organization Runtime (DOR)
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    sqlite3 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt requirements.lock* ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create non-root user and data directories
RUN groupadd -g 1000 dor && \
    useradd -u 1000 -g dor -m -s /bin/bash dor && \
    mkdir -p /app/data /app/logs && \
    chown -R dor:dor /app

USER dor

# Default exposure
EXPOSE 8000 8501

# Default command runs the REST API
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
