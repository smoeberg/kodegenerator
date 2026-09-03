# Legacy compatibility image. The certified demo path uses
# docker/Dockerfile.runtime - superseded by docker/Dockerfile.runtime for production use.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 dor \
    && useradd --system --uid 10001 --gid dor --create-home --home-dir /home/dor dor

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY --chown=dor:dor . .

USER dor
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
