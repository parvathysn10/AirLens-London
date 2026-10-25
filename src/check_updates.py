
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import requests

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"
DB_PATH = Path("data/processed/airlens.duckdb")
RAW_DIR = Path("data/raw/measurements")

STATIONS = ["BL0", "BG1", "BQ7", "BT8"]
POLLUTANTS = ["NO2"]

FIRST_DATE = date(2026, 10, 1)
OVERLAP_DAYS = 2


def get_latest_date(con, site_code, pollutant):
    result = con.execute(
        """
        SELECT MAX(CAST(measured_at AS DATE))
        FROM measurements
        WHERE site_code = ?
          AND pollutant_code = ?
        """,
        [site_code, pollutant]
    ).fetchone()

    return result[0]


def fetch_json(endpoint):
    url = f"{BASE_URL}/{endpoint}"

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    return response.json()


def save_json(data, filepath):
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def main():
    if not DB_PATH.exists():
        print("Database not found. Run transform.py first.")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        end_date = datetime.now(timezone.utc).date()
        run_time = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

        print("AIRLENS - INCREMENTAL EXTRACTION")
        print(f"End date: {end_date} (exclusive)")
        print(f"Overlap: {OVERLAP_DAYS} days\n")

        for site_code in STATIONS:
            for pollutant in POLLUTANTS:
                latest_date = get_latest_date(
                    con, site_code, pollutant
                )

                if latest_date is None:
                    start_date = FIRST_DATE
                else:
                    start_date = latest_date - timedelta(
                        days=OVERLAP_DAYS
                    )

                start_date = max(start_date, FIRST_DATE)

                if start_date >= end_date:
                    print(f"No completed days to fetch for {site_code}")
                    continue

                endpoint = (
                    f"Data/SiteSpecies/SiteCode={site_code}/"
                    f"SpeciesCode={pollutant}/"
                    f"StartDate={start_date}/EndDate={end_date}/Json"
                )

                data = fetch_json(endpoint)

                filename = (
                    f"{site_code}_{pollutant}_"
                    f"{start_date}_{end_date}_"
                    f"{run_time}.json"
                )

                filepath = RAW_DIR / filename
                save_json(data, filepath)

                readings = data.get("RawAQData", {}).get("Data", [])
                if isinstance(readings, dict):
                    readings = [readings]

                print(
                    f"{site_code} {pollutant}: "
                    f"{len(readings)} rows saved"
                )

        print("\nIncremental extraction complete")
        print("Run python src/transform.py to update DuckDB.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
