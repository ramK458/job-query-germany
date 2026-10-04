"""AFA Job Scraper — one codebase for local runs and GCP deployments.

Run modes
---------
``RUN_ENV=local`` (default) writes the workbook to ``./output/`` and needs no
Google Cloud access. ``RUN_ENV=gcp`` writes it to a Google Drive folder using
Application Default Credentials (the runtime service account on GCP, or
``gcloud auth application-default login`` locally).

Usage:
  RUN_ENV=local python main.py          # local  -> ./output/
  RUN_ENV=gcp   python main.py          # cloud  -> Google Drive
  (deployed)    main(request)           # Cloud Functions / Cloud Run entry point

Switching modes is a build/deploy concern, not a source edit: set ``RUN_ENV``
in the environment (see the Dockerfile and docs/DEPLOYMENT.md).
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import excel_generator
import job_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# "local" → writes ./output/   |   "gcp" → writes to Google Drive
# Override at runtime with the RUN_ENV environment variable (see Dockerfile).
DEFAULT_RUN_ENV = "local"
VALID_RUN_ENVS = ("local", "gcp")
RUN_ENV = os.environ.get("RUN_ENV", DEFAULT_RUN_ENV)
INITIAL_LOOKBACK_DAYS = 28   # 4 weeks for the first/backfill run; later runs are weekly
MAX_LOOKBACK_DAYS = 100      # AFA hard limit
LAST_SUCCESS_KEY = "lastSuccessfulRunUtc"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR") or Path(__file__).resolve().parent / "output")


def _resolve_run_env(run_env: str | None) -> str:
    """Normalize and validate the requested run mode."""
    value = (run_env or os.environ.get("RUN_ENV") or DEFAULT_RUN_ENV).strip().lower()
    if value not in VALID_RUN_ENVS:
        raise ValueError(f"RUN_ENV must be one of {VALID_RUN_ENVS}, got {value!r}")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lookback_days(last_success: str | None, run_until: datetime) -> int:
    """Translate the saved checkpoint into AFA's integer-day lookback."""
    if not last_success:
        return INITIAL_LOOKBACK_DAYS
    since = _parse_timestamp(last_success)
    elapsed = run_until - since
    if elapsed.total_seconds() < 0:
        raise ValueError("last successful run is in the future")
    days = max(0, math.ceil(elapsed.total_seconds() / timedelta(days=1).total_seconds()))
    if days > MAX_LOOKBACK_DAYS:
        raise ValueError(
            f"last successful run is {days} days old; AFA supports at most {MAX_LOOKBACK_DAYS} days"
        )
    return days


# ------------------------------------------------------------------
# Core logic — shared between local and GCP modes
# ------------------------------------------------------------------

def _run(run_env: str | None = None) -> tuple[int, str]:
    """Load config, scrape AFA, write results. Returns (status_code, message)."""
    try:
        run_env = _resolve_run_env(run_env)
    except ValueError as e:
        return 500, str(e)

    config_path = Path(__file__).resolve().parent / "config" / "role_titles.json"
    try:
        with open(config_path) as f:
            config = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return 500, f"Config load failed: {e}"

    groups = config["groups"]
    fname = config["master_file_name"]

    run_until = _utc_now()
    checkpoint = _format_timestamp(run_until)

    # --- LOCAL: write to ./output/ ---
    if run_env == "local":
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / fname
        checkpoint_path = OUTPUT_DIR / f".{fname}.last-success"
        exists = path.exists()

        try:
            last_success = checkpoint_path.read_text().strip() if checkpoint_path.exists() else None
            days = _lookback_days(last_success, run_until)
            data, total = _scrape(groups, days)
        except job_scraper.AuthError as e:
            logger.error("AFA rejected the request: %s", e)
            return 502, f"AFA authentication/endpoint error; checkpoint unchanged: {e}"
        except (job_scraper.ScrapeError, ValueError) as e:
            logger.error("Local scrape failed: %s", e)
            return 502, f"Scrape failed; checkpoint unchanged: {e}"
        except Exception as e:
            logger.exception("Local run failed")
            return 500, f"Local run failed; checkpoint unchanged: {e}"

        if not (exists and total == 0):
            wb = excel_generator.append_to_workbook(path.read_bytes(), data) if exists \
                 else excel_generator.create_new_workbook(data)
            path.write_bytes(wb)
        checkpoint_path.write_text(checkpoint)
        verb = "Appended" if exists else "Created"
        return 200, f"{verb} '{fname}' with {total} fetched jobs through {checkpoint} (local)."

    # --- GCP: write to Google Drive ---
    fid = os.environ.get("DRIVE_FOLDER_ID") or config.get("drive_folder_id")
    if not fid or fid == "YOUR_GOOGLE_DRIVE_FOLDER_ID":
        return 500, "Drive folder ID not configured."

    # Imported lazily: RUN_ENV=local must not require the Google Cloud libraries.
    import drive_client

    try:
        drive = drive_client.DriveClient()
        existing_id = drive.file_exists(fid, fname)
    except Exception as e:
        return 500, f"Drive init/check error: {e}"

    if existing_id is None:
        try:
            data, total = _scrape(groups, _lookback_days(None, run_until))
            drive.create_file(
                fid,
                fname,
                excel_generator.create_new_workbook(data),
                app_properties={LAST_SUCCESS_KEY: checkpoint},
            )
        except job_scraper.AuthError as e:
            logger.error("AFA rejected the request: %s", e)
            return 502, f"AFA authentication/endpoint error; checkpoint not recorded: {e}"
        except Exception as e:
            logger.exception("Initial run failed")
            return 500, f"Initial scrape/create failed; checkpoint not recorded: {e}"
        return 200, f"Created '{fname}' with {total} jobs through {checkpoint}."

    try:
        wb_bytes = drive.download_file(existing_id)
        last_success = drive.get_app_property(existing_id, LAST_SUCCESS_KEY)
        days = _lookback_days(last_success, run_until)
        data, total = _scrape(groups, days)
    except job_scraper.AuthError as e:
        logger.error("AFA rejected the request: %s", e)
        return 502, f"AFA authentication/endpoint error; checkpoint unchanged: {e}"
    except Exception as e:
        logger.exception("Incremental read/scrape failed")
        return 500, f"Incremental read/scrape failed; checkpoint unchanged: {e}"

    if total == 0:
        try:
            drive.update_app_properties(existing_id, {LAST_SUCCESS_KEY: checkpoint})
        except Exception as e:
            return 500, f"Checkpoint update failed: {e}"
        return 200, f"No jobs returned; checkpoint advanced to {checkpoint}."

    try:
        drive.update_file(
            existing_id,
            excel_generator.append_to_workbook(wb_bytes, data),
            app_properties={LAST_SUCCESS_KEY: checkpoint},
        )
    except Exception as e:
        return 500, f"Workbook append/upload failed; checkpoint unchanged: {e}"
    return 200, f"Processed {total} fetched jobs through {checkpoint} into '{fname}'."


def _scrape(groups: list[dict], days: int) -> tuple[dict[str, list[dict]], int]:
    """Scrape all groups/titles from AFA API. Returns (groups_data, total_jobs)."""
    data, total = {}, 0
    for g in groups:
        jobs = job_scraper.search_all_titles(g["titles"], days)
        data[g["name"]] = jobs
        total += len(jobs)
        logger.info("Group '%s': %d jobs", g["name"], len(jobs))
    return data, total


# ------------------------------------------------------------------
# HTTP entry point — Cloud Functions, Cloud Run, and functions-framework
# ------------------------------------------------------------------

def main(request):
    """HTTP entry point. The run mode comes from the RUN_ENV environment variable,
    so the same image serves local HTTP testing and the deployed service."""
    import flask
    status, msg = _run()
    (logger.info if status == 200 else logger.error)("%s: %s", "SUCCESS" if status == 200 else "FAILURE", msg)
    return flask.Response(json.dumps({"status": "ok" if status == 200 else "error", "message": msg}),
                          status=status, content_type="application/json")


# ------------------------------------------------------------------
# Standalone entry point (python main.py)
# ------------------------------------------------------------------

if __name__ == "__main__":
    status, msg = _run()
    icon = "✅" if status == 200 else "❌"
    print(f"{icon} [{status}] {msg}")
    raise SystemExit(0 if status == 200 else 1)
