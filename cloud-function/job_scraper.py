"""AFA (Bundesagentur für Arbeit) job search API client.

Endpoint note
-------------
The public Jobsuche API is versioned. Only ``/pc/v6/jobs`` is currently
served. The legacy paths ``/pc/v2/app/jobs`` and ``/pc/v4/app/jobs`` answer
HTTP 403 with an empty body for *every* request (verified 2026-09-29), which
is why older builds reported "403" for most search terms. A 403 is also
returned when the API key is missing, so both cases are treated as a
non-retryable configuration error.
"""

import logging
import math
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
SEARCH_PATH = "/pc/v6/jobs"

# Public demo key published by the Bundesagentur für Arbeit for the Jobsuche API.
API_KEY = "jobboerse-jobsuche"

HEADERS = {
    "X-API-Key": API_KEY,
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

PAGE_SIZE = 100          # AFA rejects size > 100 with HTTP 400
MAX_LOOKBACK_DAYS = 100  # AFA silently clamps larger values
DELAY = 1.0              # polite pause between successive API calls
MAX_RETRIES = 3
TIMEOUT = 30

# 401/403 are configuration problems — retrying wastes time and hides the cause.
AUTH_STATUS = frozenset({401, 403})
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# verguetungsangabe -> unit suffix used when rendering the Salary Range column.
PERIOD_SUFFIX = {
    "JAHRESGEHALT": "year",
    "MONATSGEHALT": "month",
    "STUNDENLOHN": "hour",
    "TAGESLOHN": "day",
}


class ScrapeError(RuntimeError):
    """Raised when a complete search cannot be obtained safely."""


class AuthError(ScrapeError):
    """Raised when the AFA API rejects our credentials or the endpoint path."""


def _format_amount(value: float) -> str:
    """Render a salary amount without trailing float noise (74999.97 -> 75,000)."""
    if value >= 1000:
        return f"{round(value):,}"
    text = f"{value:,.1f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _format_salary(raw: dict) -> str:
    """Build the human-readable Salary Range cell from a v6 record.

    Returns ``"N/A"`` when the employer published no figure.
    """
    low = raw.get("gehaltsspanneVon")
    high = raw.get("gehaltsspanneBis")
    if low is None and high is None:
        return "N/A"

    suffix = PERIOD_SUFFIX.get(raw.get("verguetungsangabe") or "")
    unit = f"EUR / {suffix}" if suffix else "EUR"

    if low is not None and high is not None:
        low_s, high_s = _format_amount(float(low)), _format_amount(float(high))
        body = low_s if low_s == high_s else f"{low_s} \u2013 {high_s}"
    elif low is not None:
        body = f"from {_format_amount(float(low))}"
    else:
        body = f"up to {_format_amount(float(high))}"
    return f"{body} {unit}"


def _get_page(phrase: str, days: int, page: int) -> dict:
    """Fetch one result page, retrying only transient failures."""
    params = {
        "was": phrase,
        "angebotsart": "1",      # 1 = regular employment
        "arbeitszeit": "vz",     # vz = full-time
        "veroeffentlichtseit": days,
        "page": page,
        "size": PAGE_SIZE,
    }

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                f"{BASE_URL}{SEARCH_PATH}", headers=HEADERS, params=params, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    last_error = exc
                else:
                    if not isinstance(payload, dict):
                        last_error = ValueError("response JSON is not an object")
                    else:
                        return payload
            elif response.status_code in AUTH_STATUS:
                # Fail fast: the endpoint path is wrong or the API key is rejected.
                raise AuthError(
                    f"AFA rejected the request with HTTP {response.status_code} for "
                    f"'{phrase}'. Check that SEARCH_PATH is '{SEARCH_PATH}' and that "
                    f"the X-API-Key header is set."
                )
            elif response.status_code not in RETRYABLE_STATUS:
                # Other 4xx (e.g. 400 for a bad parameter) will not fix themselves.
                raise ScrapeError(
                    f"AFA returned HTTP {response.status_code} for '{phrase}' "
                    f"page {page}: {response.text[:200]}"
                )
            else:
                last_error = RuntimeError(f"HTTP {response.status_code}")

        logger.warning(
            "Attempt %d/%d failed for '%s' page %d: %s",
            attempt, MAX_RETRIES, phrase, page, last_error,
        )
        if attempt < MAX_RETRIES:
            time.sleep(2 ** (attempt - 1))

    raise ScrapeError(
        f"AFA request failed for '{phrase}' page {page} after {MAX_RETRIES} attempts: {last_error}"
    )


def _to_job(phrase: str, raw: dict) -> dict:
    """Normalize one v6 result into the workbook schema."""
    refnr = str(raw.get("referenznummer") or "")
    locations = raw.get("stellenlokationen") or []
    address = (locations[0].get("adresse") or {}) if locations else {}
    entry_period = raw.get("eintrittszeitraum") or {}
    return {
        "search_term": phrase,
        "titel": raw.get("stellenangebotsTitel", ""),
        "arbeitgeber": raw.get("firma") or "N/A",
        "ort": address.get("ort") or "N/A",
        "gehalt": _format_salary(raw),
        "refnr": refnr,
        "eintrittsdatum": entry_period.get("von") or "N/A",
        "veroeffentlichungsdatum": raw.get("datumErsteVeroeffentlichung") or "N/A",
        "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}" if refnr else "",
    }


def search_jobs(phrase: str, days: int = 7) -> list[dict]:
    """Query AFA API for jobs matching *phrase* within *days* lookback.

    Fetches every result page. Any incomplete query raises ``ScrapeError`` so the
    caller cannot accidentally record a successful checkpoint with missing data.
    """
    if not 0 <= days <= MAX_LOOKBACK_DAYS:
        raise ValueError(f"days must be between 0 and {MAX_LOOKBACK_DAYS}")

    first = _get_page(phrase, days, page=1)
    raw_jobs = list(first.get("ergebnisliste") or [])
    total = int(first.get("maxErgebnisse") or len(raw_jobs))
    page_count = max(1, math.ceil(total / PAGE_SIZE))
    for page in range(2, page_count + 1):
        time.sleep(DELAY)
        raw_jobs.extend(_get_page(phrase, days, page=page).get("ergebnisliste") or [])

    results = [_to_job(phrase, raw) for raw in raw_jobs]
    logger.info("'%s' (days=%s): %d results", phrase, days, len(results))
    return results


def search_all_titles(titles: list[str], days: int = 7) -> list[dict]:
    """Query AFA for each title in *titles*, deduplicating by refnr, with rate limiting."""
    seen: set[str] = set()
    all_jobs: list[dict] = []
    for idx, phrase in enumerate(titles, 1):
        logger.info("[%d/%d] '%s' (days=%d)", idx, len(titles), phrase, days)
        time.sleep(DELAY)
        for job in search_jobs(phrase, days):
            refnr = job.get("refnr", "")
            if (refnr and refnr not in seen) or not refnr:
                seen.add(refnr)
                all_jobs.append(job)
    logger.info("%d unique jobs across %d titles", len(all_jobs), len(titles))
    return all_jobs
