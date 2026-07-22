"""AFA (Bundesagentur für Arbeit) job search API client."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {"X-API-Key": "jobboerse-jobsuche", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DELAY = 1.0


def search_jobs(phrase: str, days: int = 7) -> list[dict]:
    """Query AFA API for jobs matching *phrase* within *days* lookback.

    Returns list of dicts with keys: search_term, titel, arbeitgeber, ort, refnr, eintrittsdatum, url.
    """
    try:
        res = requests.get(f"{BASE_URL}/pc/v4/app/jobs", headers=HEADERS,
                           params={"was": phrase, "angebotsart": "1", "arbeitszeit": "vz",
                                   "veroeffentlichtseit": days, "size": 50}, timeout=15)
        if res.status_code != 200:
            logger.warning("HTTP %s for '%s' (days=%s)", res.status_code, phrase, days)
            return []
        raw = res.json().get("stellenangebote", [])
    except requests.RequestException as e:
        logger.error("Request failed for '%s': %s", phrase, e)
        return []

    results = []
    for job in raw:
        refnr = str(job.get("refnr", ""))
        results.append({
            "search_term": phrase,
            "titel": job.get("titel", ""),
            "arbeitgeber": job.get("arbeitgeber", "N/A"),
            "ort": (job.get("arbeitsort") or {}).get("ort", "N/A"),
            "refnr": refnr,
            "eintrittsdatum": job.get("eintrittsdatum", "N/A"),
            "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}" if refnr else "",
        })
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
