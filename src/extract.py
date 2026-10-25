
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"

RAW_DIR = Path("data/raw")

START_DATE = "2026-10-01"
END_DATE = "2026-10-08"

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


def extract_measurements():
    for site_code, site_name in STATIONS.items():
        for pollutant in POLLUTANTS:
            endpoint = (
                f"Data/SiteSpecies/SiteCode={site_code}/"
                f"SpeciesCode={pollutant}/"
                f"StartDate={START_DATE}/EndDate={END_DATE}/Json"
            )

            data = fetch_json(endpoint)

            filename = (
                f"{site_code}_{pollutant}_"
                f"{START_DATE}_{END_DATE}.json"
            )

            filepath = RAW_DIR / "measurements" / filename
            save_json(data, filepath)

            readings = data.get("RawAQData", {}).get("Data", [])
            if isinstance(readings, dict):
                readings = [readings]

            print(
                f"Saved {site_name} ({site_code}) "
                f"{pollutant}: {len(readings)} rows"
            )


def main():
    print("Starting AirLens extraction\n")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    extract_sites()
    extract_site_species()
    extract_measurements()

    print("\nExtraction complete")


if __name__ == "__main__":
    main()
