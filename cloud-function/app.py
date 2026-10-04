"""WSGI entry point for Cloud Run.

Cloud Functions invokes ``main.main(request)`` directly. Cloud Run needs a
WSGI application to hand to gunicorn, so this module wraps the same entry
point — there is no duplicated scraping logic here.

Local check::

    RUN_ENV=local gunicorn --bind :8080 app:app
    curl -i localhost:8080/

Deployed, Cloud Scheduler calls ``/`` once per run; ``/healthz`` is a cheap
liveness probe that never triggers a scrape.
"""

from flask import Flask, request

import main as scraper

app = Flask(__name__)


@app.get("/")
@app.post("/")
def run_scraper():
    """Trigger one scrape. The destination comes from the RUN_ENV variable."""
    return scraper.main(request)


@app.get("/healthz")
def healthz():
    """Liveness probe — deliberately does not touch AFA or Drive."""
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
