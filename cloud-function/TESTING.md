# Local Testing Guide

How to test the AFA job scraper on your machine without deploying to GCP.

---

## Quick Start

```bash
# 1. Set up
cd cloud-function/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Run the scraper locally — that's it
python main.py

# 3. Inspect the output
open output/job_listings_master.xlsx
```

On first run, the scraper queries the AFA API with a **45-day** lookback and creates a new workbook in `output/`. Run it again to see it append with a **7-day** lookback instead.

---

## 1. Environment Setup

```bash
cd cloud-function/

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# (Optional) Install the Functions Framework for HTTP testing
pip install functions-framework
```

### Verify dependencies

```bash
python -c "
import openpyxl, requests, google.auth, googleapiclient
print('All dependencies OK')
"
```

---

## 2. Run the Scraper Locally

### Option A — Basic run

```bash
python main.py
```

**Expected output (initial run):**
```
INFO:__main__:Group 'Radar Engineers': 12 jobs
INFO:__main__:Group 'Perception Engineers': 8 jobs
INFO:__main__:Group 'system integration': 5 jobs
✅ [200] Created 'job_listings_master.xlsx' with 25 jobs (local).
```

### Option B — Run with the HTTP server (simulates Cloud Functions runtime)

```bash
# Terminal 1 — start the server
pip install functions-framework
functions-framework --target main --debug --port 8080
```

```bash
# Terminal 2 — trigger the function
curl -X GET http://localhost:8080
```

### Option C — Verbose debug logging

```bash
python -c "
import logging
logging.basicConfig(level=logging.DEBUG, force=True)
exec(open('main.py').read())
"
```

---

## 3. Run It Twice — Test Incremental Append

The local `output/` directory persists between runs, so you can test the full create-then-append cycle:

```bash
# Clean slate
rm -rf cloud-function/output/

# Run 1 — initial scrape (45-day lookback) → creates workbook
python main.py

# Check the file size
ls -lh cloud-function/output/

# Run 2 — incremental scrape (7-day lookback) → appends to workbook
python main.py

# Run 3 — if no new jobs, skips update
python main.py
```

Expected cycle:

| Run | Mode | Behavior |
|-----|------|----------|
| 1st | Initial | Creates `output/job_listings_master.xlsx` with 45-day data |
| 2nd | Incremental | Appends 7-day data to the existing file |
| 3rd+ | Incremental | "No new jobs found" if nothing changed |

---

## 4. Inspect the Output Workbook

### Check sheet names and row counts

```bash
RUN_ENV=local python -c "
import openpyxl
wb = openpyxl.load_workbook('output/job_listings_master.xlsx')
for name in wb.sheetnames:
    ws = wb[name]
    print(f'{name}: {ws.max_row - 1} jobs')
"
```

### Dump contents to the terminal

```bash
RUN_ENV=local python -c "
import openpyxl
wb = openpyxl.load_workbook('output/job_listings_master.xlsx')
ws = wb.active
for row in ws.iter_rows(values_only=True):
    print(' | '.join(str(c) for c in row))
"
```

### Open in Excel

```bash
open output/job_listings_master.xlsx     # macOS
# xdg-open output/job_listings_master.xlsx  # Linux
# start output/job_listings_master.xlsx     # Windows
```

---

## 5. Unit-Test Individual Modules

### Test the AFA scraper

```bash
python -c "
from job_scraper import search_jobs, search_all_titles

# Single phrase, 45-day window
jobs = search_jobs('radar perception', days=45)
print(f'Found {len(jobs)} jobs for radar perception')

# Multiple titles with dedup
titles = ['radar perception', 'radar']
all_jobs = search_all_titles(titles, days=7)
print(f'Found {len(all_jobs)} unique jobs across {len(titles)} titles')

# Inspect the first result
if all_jobs:
    print('Sample job:', all_jobs[0])
"
```

### Test the Excel generator with mock data

```bash
python -c "
from excel_generator import create_new_workbook, append_to_workbook

mock_data = {
    'Test Group': [
        {'search_term': 'radar', 'titel': 'Radar Engineer',
         'arbeitgeber': 'Bosch', 'ort': 'Stuttgart',
         'refnr': '12345', 'eintrittsdatum': '2026-07-01',
         'url': 'https://example.com/12345'}
    ]
}

# Create a workbook
wb_bytes = create_new_workbook(mock_data)
print(f'Created workbook: {len(wb_bytes)} bytes')

# Append to it (simulates 2nd run)
more_data = {
    'Test Group': [
        {'search_term': 'radar', 'titel': 'Sr Radar Engineer',
         'arbeitgeber': 'Continental', 'ort': 'Frankfurt',
         'refnr': '67890', 'eintrittsdatum': '2026-07-15',
         'url': 'https://example.com/67890'}
    ]
}
wb_bytes = append_to_workbook(wb_bytes, more_data)
print(f'Appended workbook: {len(wb_bytes)} bytes')
print('OK — no errors')
"
```

### Test deduplication (refnr already exists)

```bash
python -c "
from excel_generator import create_new_workbook, append_to_workbook
from io import BytesIO
import openpyxl

data = {
    'Test': [
        {'search_term': 'radar', 'titel': 'Radar Engineer',
         'arbeitgeber': 'Bosch', 'ort': 'Stuttgart',
         'refnr': '12345', 'eintrittsdatum': '2026-07-01',
         'url': 'https://example.com/12345'}
    ]
}
wb = create_new_workbook(data)

# Try appending the same job again (same refnr) — should be skipped
wb = append_to_workbook(wb, data)

# Verify only 1 row
wb2 = openpyxl.load_workbook(BytesIO(wb))
ws = wb2['Test']
row_count = ws.max_row - 1  # minus header
print(f'Rows after duplicate append attempt: {row_count}')
assert row_count == 1, f'Expected 1, got {row_count}'
print('✅ Dedup works correctly')
"
```

### Test the Drive client mock (for isolated testing)

```bash
python -c "
from drive_client import DriveClient
# In local mode, DriveClient is not used — but verify import works
print('DriveClient imported OK')
print('Methods:', [m for m in dir(DriveClient) if not m.startswith('_')])
"
```

---

## 6. Mock the AFA API (Offline Testing)

To test the full pipeline **without** hitting the real AFA API, monkey-patch the scraper module before importing main:

```bash
python -c "
from unittest.mock import patch
import job_scraper

fake = [{'search_term': 'radar', 'titel': 'Fake Engineer',
         'arbeitgeber': 'Fake Corp', 'ort': 'Berlin',
         'refnr': 'FAKE001', 'eintrittsdatum': '2026-07-22',
         'url': 'https://example.com/FAKE001'}]

with patch.object(job_scraper, 'search_all_titles', return_value=fake):
    import main
    main._run()

# Check the output
import openpyxl
wb = openpyxl.load_workbook('output/job_listings_master.xlsx')
ws = wb.active
print(f'Sheet: {ws.title}, Rows: {ws.max_row}')
for row in ws.iter_rows(values_only=True):
    print(row)
"
```

---

## 7. Test Edge Cases

### No jobs found

```bash
python -c "
from unittest.mock import patch
import job_scraper

with patch.object(job_scraper, 'search_all_titles', return_value=[]):
    import main
    status, msg = main._run()
    print(f'[{status}] {msg}')
    # Expected: [200] No new jobs found. Workbook unchanged.
"
```

### Config file missing

```bash
cd cloud-function/
python -c "
import os, main
os.rename('config/role_titles.json', 'config/role_titles.json.bak')
status, msg = main._run()
print(f'[{status}] {msg}')
os.rename('config/role_titles.json.bak', 'config/role_titles.json')
# Expected: [500] Config load failed: ...
"
```

### Invalid JSON in config

```bash
cd cloud-function/
python -c "
import os, shutil, main

shutil.copy('config/role_titles.json', 'config/role_titles.json.bak')
with open('config/role_titles.json', 'w') as f:
    f.write('{invalid json')

status, msg = main._run()
print(f'[{status}] {msg}')
shutil.move('config/role_titles.json.bak', 'config/role_titles.json')
# Expected: [500] Config load failed: ...
"
```

---

## 8. Clean Up

```bash
# Remove local test output
rm -rf cloud-function/output/

# Deactivate virtual environment
deactivate
```

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'flask'` | Dependencies not installed | `pip install -r requirements.txt` |
| `Import "flask" could not be resolved` | Local linter warning only | Safe to ignore — Flask is bundled in Cloud Functions runtime |
| `RUN_ENV=local not working` | Wrong working directory | Run commands from `cloud-function/` |
| `openpyxl` errors | Corrupted output file | `rm -rf output/` and re-run |
| No jobs returned | AFA API may have no results for your terms | Test with `search_jobs('ingenieur', days=45)` |
| `functions-framework: command not found` | Not installed | `pip install functions-framework` |
