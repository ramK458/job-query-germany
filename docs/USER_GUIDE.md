# User Guide — AFA Job Scraper

Collects job postings from the German Federal Employment Agency
(**Bundesagentur für Arbeit**, "AFA") for a set of role-title groups and writes
them into one Excel workbook — one sheet per group, with clickable links, salary
ranges and dates.

You can run it on your own Mac, or let it run weekly on Google Cloud and drop the
workbook into Google Drive.

---

## 1. Quick start (macOS, Apple Silicon)

```bash
cd job-query-germany/cloud-function

# 1. Create the virtual environment and install dependencies
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Run it
python main.py

# 3. Open the result
open output/job_listings_master.xlsx
```

That is the whole workflow. The first run creates the workbook; every later run
appends only what is new.

> **Use Python 3.12.** It matches the deployed runtime (`python312`) and is the
> version the dependencies are tested against. On an M-series Mac
> `/usr/local/bin/python3.12` and `/opt/homebrew/bin/python3.12` both work.

**Check your setup** before a long run:

```bash
python -c "import openpyxl, requests; print('dependencies OK')"
```

If this fails, the virtual environment is not active — run
`source .venv/bin/activate` first.

---

## 2. What a run produces

```
cloud-function/output/
├── job_listings_master.xlsx              # the workbook
└── .job_listings_master.xlsx.last-success  # checkpoint (hidden)
```

The checkpoint records when the last successful run finished. It is what makes
runs incremental — do not delete it unless you *want* a full re-scrape.

### Workbook layout

One sheet per group in `config/role_titles.json`. Every sheet has the same nine
columns:

| # | Column | Contents |
|---|---|---|
| A | Role Title | The search phrase that found this posting |
| B | Job Title | Position title |
| C | Company Name | Employer (`N/A` if the API omits it) |
| D | Location | City of the first listed workplace |
| E | Salary Range | e.g. `60,000 – 70,000 EUR / year`, else `N/A` |
| F | Link | Clickable link to the posting on arbeitsagentur.de |
| G | Job ID | AFA reference number (used for de-duplication) |
| H | Start Date | Earliest possible start date, else `N/A` |
| I | Posted Date | Date the posting first appeared |

The header row is frozen and carries a filter, so you can sort and filter every
column — including by salary once you widen column E.

### About the Salary column

Most German postings do not state pay. In a typical run roughly **20–25 %** of
rows have a salary; the rest show `N/A`. That is the source data, not a bug.

Rendering rules:

| API data | Displayed as |
|---|---|
| Range 60000–70000, annual | `60,000 – 70,000 EUR / year` |
| Range 29.5–36.4, hourly | `29.5 – 36.4 EUR / hour` |
| Identical low/high | `69,000 EUR / year` |
| Only a lower bound | `from 60,000 EUR` |
| No figure published | `N/A` |

---

## 3. Configuration

Everything lives in `cloud-function/config/role_titles.json`:

```json
{
  "master_file_name": "job_listings_master.xlsx",
  "groups": [
    {
      "name": "Radar Signal & Algorithms",
      "titles": ["radar signalverarbeitung", "radar signal processing", "radar algorithmen"]
    }
  ]
}
```

- **`groups[].name`** becomes a sheet name. Characters `[ ] : * ? / \` are
  replaced with `-`, and names are truncated to Excel's 31-character limit.
  Keep names under 31 characters so they survive intact.
- **`groups[].titles`** are the search phrases sent to the API. Each is queried
  separately and results are de-duplicated within the group.
- A posting matching several titles is stored **once per sheet**, with the first
  matching phrase as its Role Title. The same posting can legitimately appear on
  two different sheets.

Adding a group or title never breaks existing sheets — new sheets are created on
the next run.

> **Renaming a group leaves the old sheet behind.** Sheets are matched by name,
> so renaming `Radar Engineers` to `Radar Signal & Algorithms` makes the next run
> create a *second* sheet and keep the old one. After renaming groups, start
> clean: `rm -rf output/` and re-run.

### The shipped groups

The default configuration targets radar engineering plus autonomous perception:

| Sheet | Focus | Typical rows |
|---|---|---|
| `Radar Signal & Algorithms` | DSP, signal processing, tracking, MIMO | ~31 |
| `Radar Software & Embedded` | Software/firmware development for radar | ~41 |
| `Radar System Engineering` | System-level radar engineering | ~90 |
| `Perception & Sensor Fusion` | Perception, sensor/lidar fusion, ADAS | ~139 |

Row counts are from a 4-week window and drift with the market.

### How the search phrases work

The API's `was` parameter **ANDs every word**:

| Phrase | Hits | Why |
|---|---|---|
| `radar` | 164 | One word, so broad |
| `radar signalverarbeitung` | 13 | Both words required |
| `radar zzzzqqqq` | 0 | No match for the nonsense word |

More words means fewer, more precise hits. Both German and English phrasings
work and often return different postings, so the groups mix them.

### Choosing phrases

| Goal | Phrases that work |
|---|---|
| Radar signal processing | `radar signalverarbeitung`, `radar signal processing`, `radar signal` |
| Radar algorithms | `radar algorithmen`, `radar algorithm`, `radar tracking`, `mimo radar` |
| Radar software/firmware | `radar software`, `radar softwareentwicklung`, `radar firmware`, `softwareentwickler radar` |
| Radar system engineering | `radar systemingenieur`, `systemingenieur radar`, `radar systems`, `radarsysteme` |
| Perception and fusion | `radar perception`, `sensor fusion`, `sensordatenfusion`, `lidar`, `adas` |

**Avoid bare German nouns.** They are not job-title specific and flood a sheet
with unrelated roles:

| Phrase | Hits | What you actually get |
|---|---|---|
| `wahrnehmung` | 2353 | Legal roles — "Wahrnehmung von Aufgaben" |
| `regelung` | 2560 | Control/accounting roles |
| `sensorik` | 1267 | Assembly and production |
| `robotik` | 846 | Installation and maintenance |
| `embedded software` | 816 | Everything embedded |
| `fahrerassistenzsysteme` | 59 | Mostly Kfz-Mechatroniker (58 % noise) |

Each phrase costs about one second of run time, plus one more per additional
page of results.

---

## 4. Running it

### Plain local run

```bash
python main.py
```

Exit code `0` on success, `1` on failure. Output ends with a one-line summary:

```
✅ [200] Created 'job_listings_master.xlsx' with 245 fetched jobs through 2026-09-29T11:02:17Z (local).
```

### Every few runs, expect a smaller append

A run only asks the API for postings published since the last checkpoint, so the
second run in a row usually adds nothing:

| Run | Lookback requested | Typical result |
|---|---|---|
| 1st (backfill) | 28 days (4 weeks) | `Created ... with ~300 fetched jobs` |
| 2nd, minutes later | 1 day | `Appended ...` with a handful of rows, often 0 new |
| After a week | 7 days | `Appended ...` with the week's new postings |

`fetched` counts rows returned by the API; `appended` counts rows actually added
after de-duplication. They differ because postings are de-duplicated by Job ID.

### Start over

```bash
rm -rf output/     # deletes the workbook and the checkpoint
python main.py     # next run does a full 4-week scrape
```

To keep the workbook but force a full re-scrape, delete only the checkpoint:

```bash
rm output/.job_listings_master.xlsx.last-success
```

### Run it as a web service (how Cloud Run calls it)

```bash
RUN_ENV=local gunicorn --bind :8080 --workers 1 --threads 4 --timeout 900 app:app

curl localhost:8080/healthz   # -> {"status":"ok"}, no scrape
curl localhost:8080/          # -> triggers a scrape, returns a JSON summary
```

### Run it in Docker

```bash
cd cloud-function

# Build natively (arm64 on an M-series Mac)
docker build -t afa-scraper:local .

# Same behaviour as `python main.py`, results land in ./output on the host
docker run --rm -e RUN_ENV=local \
    -v "$PWD/output:/app/output" afa-scraper:local python main.py

# Or as a server
docker run --rm -p 8080:8080 -e RUN_ENV=local \
    -v "$PWD/output:/app/output" afa-scraper:local
```

---

## 5. Connecting it to Google Drive

Set `RUN_ENV=gcp` and the same code writes to Drive instead of `./output/`:

```bash
RUN_ENV=gcp DRIVE_FOLDER_ID=1AbC...xyz python main.py
```

This needs credentials and a shared folder. Follow
[DEPLOYMENT.md](./DEPLOYMENT.md) — it covers the service account, the folder
sharing step, and the weekly schedule.

---

## 6. Reading the workbook

**In Excel / Numbers / LibreOffice** — just open it. Use the filter arrows in row 1.

**From the command line:**

```bash
python - <<'PY'
import openpyxl
wb = openpyxl.load_workbook('output/job_listings_master.xlsx')
for name in wb.sheetnames:
    ws = wb[name]
    priced = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r[4] != 'N/A')
    print(f'{name:22} rows={ws.max_row - 1:4}  with salary={priced}')
PY
```

**Filter to jobs that state a salary:**

```bash
python - <<'PY'
import openpyxl
ws = openpyxl.load_workbook('output/job_listings_master.xlsx')['Radar System Engineering']
for r in ws.iter_rows(min_row=2, values_only=True):
    if r[4] != 'N/A':
        print(f'{r[1][:55]:57} {r[4]:32} {r[3]}')
PY
```

---

## 7. Frequently asked questions

**How long does a run take?**
About 45 seconds for the default configuration (32 phrases). Each search phrase
takes roughly a second, plus a second per additional page of results.

**Why do I get `N/A` in most salary cells?**
Because most employers do not publish pay through this API. Roughly a fifth of
postings do; those are rendered in full.

**Why is a job missing?**
The API only returns postings published within the lookback window, filtered to
full-time regular employment (`arbeitszeit=vz`). Internships, part-time roles and
older postings are excluded by design.

**Can I get more results per phrase?**
The API caps a page at 100 results; the scraper already walks every page, so you
get all matches for the window. Widen the window by letting more time pass
between runs, or add broader phrases.

**I see `AFA authentication/endpoint error` — what now?**
The API returned 401/403. That means the endpoint path or the API key is wrong,
not a temporary glitch. Confirm `SEARCH_PATH` in `job_scraper.py` is
`/pc/v6/jobs`. Older paths (`/pc/v2/...`, `/pc/v4/...`) are retired and return
403 for every request.

**A run failed halfway. Is my data safe?**
Yes. The checkpoint is only advanced after a successful write, so the next run
re-scrapes the same window and de-duplicates by Job ID.

**Can I run it twice at once?**
No. Two runs would race on the same workbook. If you schedule it, cap
concurrency at one instance.
