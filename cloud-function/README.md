# AFA Job Scraper (Cloud Function)

Scrapes job postings from the German Federal Employment Agency
(*Bundesagentur für Arbeit*) for configurable role-title groups and writes them
into an Excel workbook with clickable links, salary ranges and dates.

The same codebase runs in two modes — the destination is chosen by the `RUN_ENV`
environment variable, never by editing source:

| `RUN_ENV` | Destination |
|---|---|
| `local` (default) | `./output/` on disk |
| `gcp` | a shared Google Drive folder |

## Documentation

| Guide | Covers |
|---|---|
| [../docs/USER_GUIDE.md](../docs/USER_GUIDE.md) | Running it locally on an M-series Mac, Docker usage, configuration, output format, FAQ |
| [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) | Building the image, Cloud Run + Cloud Scheduler, service accounts, Drive sharing, troubleshooting |
| [../docs/DEVELOPER_GUIDE.md](../docs/DEVELOPER_GUIDE.md) | Module design, the AFA API contract, tests, extending the schema, change checklist |

## Fastest possible start

```bash
cd cloud-function
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
open output/job_listings_master.xlsx
```

## Layout

| File | Role |
|---|---|
| `main.py` | Run-mode selection, checkpoint arithmetic, orchestration, HTTP entry point |
| `job_scraper.py` | AFA API client (endpoint `/pc/v6/jobs`), pagination, salary formatting |
| `excel_generator.py` | Workbook create/append, styling, links, filters, de-duplication |
| `drive_client.py` | Google Drive wrapper (used only when `RUN_ENV=gcp`) |
| `app.py` | WSGI entry point for Cloud Run / gunicorn |
| `config/role_titles.json` | Search groups, phrases and the workbook file name |
| `test_incremental.py` | Offline unit tests (`python -m unittest -v`) |
| `Dockerfile` | Single image for both run modes |

> **Note:** the AFA Jobsuche API only serves `/pc/v6/jobs`. The older
> `/pc/v2/...` and `/pc/v4/...` paths are retired and answer HTTP 403 for every
> request, which is why an older build reported "403" for most search terms.
