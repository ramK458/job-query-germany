# One image, two run modes — the destination is chosen by RUN_ENV, not by code.
#
#   Local (native, Apple Silicon) — repeats the CLI run into ./output/
#     docker build -t afa-scraper:local .
#     docker run --rm -e RUN_ENV=local -v "$PWD/output:/app/output" afa-scraper:local python main.py
#
#   GCP (must be linux/amd64 even when built on an M-series Mac)
#     docker build --platform linux/amd64 --build-arg RUN_ENV=gcp -t afa-scraper:gcp .
#
# See docs/DEPLOYMENT.md for the full deployment walkthrough.

FROM python:3.12-slim

# RUN_ENV is the single switch: "local" -> ./output/, "gcp" -> Google Drive (ADC).
ARG RUN_ENV=local
ENV RUN_ENV=${RUN_ENV} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Requirements first so the dependency layer is cached across source edits.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# RUN_ENV=local writes here; mount a volume over it to keep results on the host.
RUN mkdir -p /app/output

EXPOSE 8080

# Cloud Run injects $PORT. One worker keeps a single scrape in flight per
# instance; threads let /healthz answer while a scrape is running.
CMD ["sh", "-c", "exec gunicorn --bind :${PORT} --workers 1 --threads 4 --timeout 900 --graceful-timeout 60 app:app"]
