
import argparse
import json
from datetime import date
from pathlib import Path

import requests

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"
RAW_DIR = Path("data/raw")

STATIONS = {
    "BL0": "Camden - Bloomsbury",
    "BG1": "Barking and Dagenham - Rush Green",
    "BQ7": "Bexley - Belvedere West",
    "BT8": "Brent - ARK Franklin Primary Academy",
}

POLLUTANTS = ["NO2"]


def fetch_json(endpoint):
    url = f"{BASE_URL}/{endpoint}"

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    return response.json()


def save_json(data, filepath):
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def extract_sites():
    endpoint = "Information/MonitoringSites/GroupName=London/Json"
    data = fetch_json(endpoint)

    filepath = RAW_DIR / "monitoring_sites.json"
    save_json(data, filepath)

    print(f"Saved station metadata: {filepath}")


def extract_site_species():
    endpoint = "Information/MonitoringSiteSpecies/GroupName=London/Json"
    data = fetch_json(endpoint)

    filepath = RAW_DIR / "site_species.json"
    save_json(data, filepath)

    print(f"Saved site-pollutant metadata: {filepath}")


def extract_measurements(start_date, end_date):
    for site_code, site_name in STATIONS.items():
        for pollutant in POLLUTANTS:
            endpoint = (
                f"Data/SiteSpecies/SiteCode={site_code}/"
                f"SpeciesCode={pollutant}/"
                f"StartDate={start_date}/EndDate={end_date}/Json"
            )

            filename = (
                f"{site_code}_{pollutant}_"
                f"{start_date}_{end_date}.json"
            )

            filepath = RAW_DIR / "measurements" / filename

            if filepath.exists():
                print(f"Already saved, skipping: {filename}")
                continue

            data = fetch_json(endpoint)
            save_json(data, filepath)

            readings = data.get("RawAQData", {}).get("Data", [])

            if isinstance(readings, dict):
                readings = [readings]

            print(
                f"Saved {site_name} ({site_code}) "
                f"{pollutant}: {len(readings)} rows"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Extract London air quality data"
    )

    parser.add_argument(
        "--start",
        default="2026-10-01",
        help="Start date in YYYY-MM-DD format"
    )

    parser.add_argument(
        "--end",
        default="2026-10-08",
        help="Exclusive end date in YYYY-MM-DD format"
    )

    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    if end_date <= start_date:
        parser.error("End date must be after start date")

    print("Starting AirLens extraction")
    print(f"Period: {start_date} to {end_date} (end exclusive)\n")

    extract_sites()
    extract_site_species()
    extract_measurements(start_date, end_date)

    print("\nExtraction complete")


if __name__ == "__main__":
    main()
