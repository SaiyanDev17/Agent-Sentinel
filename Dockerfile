FROM python:3.11-slim

WORKDIR /app

# Reduce image size and improve pip install speed
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Single worker with async concurrency — Cloud Run scales horizontally.
# Startup CPU boost handles Phoenix OTEL + scenario cache preload.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-keep-alive 75 --limit-concurrency 100"]
