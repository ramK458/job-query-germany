import os
import time
import pandas as pd
import requests

# -------------------------------------------------------------------
# 1. Target Keywords (Exact List)
# -------------------------------------------------------------------
SEARCH_KEYWORDS = [
    "radar perception",
    "system designer radar",
    "systemarchitekt radar",
    "radar Signalverarbeitung",
    "perception engineer",
    "funktionsentwicklung radar",
    "radar"
]

RAW_INTERMEDIATE_CSV = "raw_keyword_jobs.csv"

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}


# -------------------------------------------------------------------
# 2. Level 1 Search Engine
# -------------------------------------------------------------------
def search_jobs_by_phrase(phrase: str) -> list:
    """Queries the Arbeitsagentur API using multi-word title phrases."""
    url = f"{BASE_URL}/pc/v4/app/jobs"
    params = {
        "was": phrase,  # Searches for partial phrase matches in job title
        "angebotsart": "1",  # 1 = Regular employment
        "arbeitszeit": "vz",  # Full-time
        "veroeffentlichtseit": 7,  # Newest jobs within last 7 days
        "size": 50,
    }

    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if res.status_code == 200:
            return res.json().get("stellenangebote", [])
        else:
            print(
                f"    [WARN] API returned HTTP {res.status_code} for term '{phrase}'"
            )
    except Exception as e:
        print(f"    [ERROR] Request failed for term '{phrase}': {e}")

    return []


def save_intermediate_batch(jobs_batch: list):
    """Appends newly found raw job records directly to the intermediate CSV file."""
    if not jobs_batch:
        return

    df_new = pd.DataFrame(jobs_batch)
    file_exists = os.path.exists(RAW_INTERMEDIATE_CSV)
    df_new.to_csv(
        RAW_INTERMEDIATE_CSV, mode="a", index=False, header=not file_exists
    )
    print(
        f"  💾 Intermediate save: Appended {len(jobs_batch)} records to '{RAW_INTERMEDIATE_CSV}'."
    )


# -------------------------------------------------------------------
# 3. Execution Loop (Level 1 Only)
# -------------------------------------------------------------------
def main():
    print("=" * 80)
    print("LEVEL 1 ONLY: Collecting raw jobs using multi-word keyword phrases")
    print(f"Targeting {len(SEARCH_KEYWORDS)} specific search phrases (Last 7 days)")
    print("=" * 80)

    seen_ref_nrs = set()

    # Load existing reference numbers if resuming
    if os.path.exists(RAW_INTERMEDIATE_CSV):
        try:
            prev_df = pd.read_csv(RAW_INTERMEDIATE_CSV)
            seen_ref_nrs = set(prev_df["Ref Number"].astype(str))
            print(
                f"ℹ️ Loaded {len(seen_ref_nrs)} existing reference numbers from checkpoint.\n"
            )
        except Exception:
            pass

    total_new_found = 0

    for idx, phrase in enumerate(SEARCH_KEYWORDS, start=1):
        print(f"\n[{idx}/{len(SEARCH_KEYWORDS)}] Querying phrase: '{phrase}'")
        time.sleep(1.0)  # Rate limit protection

        raw_jobs = search_jobs_by_phrase(phrase)
        print(f"  --> API returned {len(raw_jobs)} postings.")

        new_batch = []
        for job in raw_jobs:
            ref_nr = str(job.get("refnr", ""))

            if ref_nr and ref_nr not in seen_ref_nrs:
                seen_ref_nrs.add(ref_nr)

                # Capture basic payload info directly from search result
                job_record = {
                    "Search Term": phrase,
                    "Job Title": job.get("titel", ""),
                    "Employer": job.get("arbeitgeber", "N/A"),
                    "Location": job.get("arbeitsort", {}).get("ort", "N/A"),
                    "Posted Date": job.get("eintrittsdatum", "N/A"),
                    "Ref Number": ref_nr,
                    "URL": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref_nr}",
                }
                new_batch.append(job_record)

        if new_batch:
            save_intermediate_batch(new_batch)
            total_new_found += len(new_batch)
            print(f"  ✅ Added {len(new_batch)} new unique postings.")
        else:
            print("  ℹ️ No new unique postings for this term.")

    print("\n" + "=" * 80)
    if os.path.exists(RAW_INTERMEDIATE_CSV):
        df_final_raw = pd.read_csv(RAW_INTERMEDIATE_CSV)
        print(
            f"🎉 LEVEL 1 COMPLETE: '{RAW_INTERMEDIATE_CSV}' contains {len(df_final_raw)} total unique jobs."
        )
    else:
        print(
            "⚠️ No jobs found matching these 6 exact phrases in the last 7 days."
        )


if __name__ == "__main__":
    main()