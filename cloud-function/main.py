"""GCP Cloud Function — Weekly AFA Job Scraper.

Usage:
  python main.py                        # local — saves to output/
  (deployed) main(request)              # cloud — writes to Google Drive

Set RUN_ENV = "local" / "gcp" at the top of this file to switch modes.
In GCP mode the runtime SA authenticates via ADC (metadata server) — no key file needed.
"""

import json
import logging
from pathlib import Path

import drive_client
import excel_generator
import job_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RUN_ENV = "local"  # "local" → ./output/  |  "gcp" → Google Drive
DAYS = {"initial": 45, "incremental": 7}
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


# ------------------------------------------------------------------
# Core logic — shared between local and GCP modes
# ------------------------------------------------------------------

def _run(run_env: str | None = None) -> tuple[int, str]:
    """Load config, scrape AFA, write results. Returns (status_code, message)."""
    if run_env is None:
        run_env = RUN_ENV

    config_path = Path(__file__).resolve().parent / "config" / "role_titles.json"
    try:
        with open(config_path) as f:
            config = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return 500, f"Config load failed: {e}"

    groups = config["groups"]
    fname = config["master_file_name"]

    # --- LOCAL: write to ./output/ ---
    if run_env == "local":
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / fname
        exists = path.exists()

        days = DAYS["incremental"] if exists else DAYS["initial"]
        data, total = _scrape(groups, days)
        if exists and total == 0:
            return 200, "No new jobs found. Workbook unchanged."

        wb = excel_generator.append_to_workbook(path.read_bytes(), data) if exists \
             else excel_generator.create_new_workbook(data)
        path.write_bytes(wb)
        verb = "Appended" if exists else "Created"
        return 200, f"{verb} '{fname}' with {total} jobs (local)."

    # --- GCP: write to Google Drive ---
    fid = config["drive_folder_id"]
    if not fid or fid == "YOUR_GOOGLE_DRIVE_FOLDER_ID":
        return 500, "Drive folder ID not configured."

    try:
        drive = drive_client.DriveClient()
        existing_id = drive.file_exists(fid, fname)
    except Exception as e:
        return 500, f"Drive init/check error: {e}"

    if existing_id is None:
        data, total = _scrape(groups, DAYS["initial"])
        try:
            drive.create_file(fid, fname, excel_generator.create_new_workbook(data))
        except Exception as e:
            return 500, f"Workbook create/upload error: {e}"
        return 200, f"Created '{fname}' with {total} jobs across {len(data)} groups."

    try:
        wb_bytes = drive.download_file(existing_id)
    except Exception as e:
        return 500, f"Download error: {e}"

    data, total = _scrape(groups, DAYS["incremental"])
    if total == 0:
        return 200, "No new jobs found. Workbook unchanged."

    try:
        drive.update_file(existing_id, excel_generator.append_to_workbook(wb_bytes, data))
    except Exception as e:
        return 500, f"Workbook append/upload error: {e}"
    return 200, f"Appended {total} new jobs to '{fname}'."


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
# Cloud Function HTTP entry point (deployed to GCP)
# ------------------------------------------------------------------

def main(request):
    """HTTP-triggered Cloud Function entry point — always uses GCP."""
    import flask
    status, msg = _run(run_env="gcp")
    (logger.info if status == 200 else logger.error)("%s: %s", "SUCCESS" if status == 200 else "FAILURE", msg)
    return flask.Response(json.dumps({"status": "ok" if status == 200 else "error", "message": msg}),
                          status=status, content_type="application/json")


# ------------------------------------------------------------------
# Standalone entry point (RUN_ENV=local python main.py)
# ------------------------------------------------------------------

if __name__ == "__main__":
    status, msg = _run()
    icon = "✅" if status == 200 else "❌"
    print(f"{icon} [{status}] {msg}")
