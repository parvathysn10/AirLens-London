
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
    """Fetch JSON from LAQN, retrying temporary network/server failures."""
    url = f"{BASE_URL}/{endpoint}"

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    with requests.Session() as session:
        session.mount(
            "https://",
            HTTPAdapter(max_retries=retry_strategy),
        )

        response = session.get(url, timeout=60)
        response.raise_for_status()
        return response.json()


def validate_measurement_response(data, site_code, pollutant):
    """
    Check the basic structure of an LAQN measurement response.

    Empty or missing Data is allowed because a station may have
    no measurements for the requested period.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid API response for {site_code}/{pollutant}: "
            "expected a JSON object"
        )

    raw = data.get("RawAQData")

    if not isinstance(raw, dict):
        raise ValueError(
            f"Invalid API response for {site_code}/{pollutant}: "
            "missing RawAQData object"
        )

    if raw.get("@SiteCode") != site_code:
        raise ValueError(
            f"Unexpected station code in API response: {site_code}"
        )

    if raw.get("@SpeciesCode") != pollutant:
        raise ValueError(
            f"Unexpected pollutant code in API response: {pollutant}"
        )

    readings = raw.get("Data")

    if readings is None:
        return []

    if isinstance(readings, dict):
        return [readings]

    if isinstance(readings, list):
        return readings

    raise ValueError(
        f"Invalid measurements for {site_code}/{pollutant}: "
        "Data must be a list, object or null"
    )


def save_json(data, filepath):
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def extract_sites():
    endpoint = "Information/MonitoringSites/GroupName=London/Json"
    data = fetch_json(endpoint)

    if not isinstance(data, dict) or not isinstance(
        data.get("Sites"), dict
    ):
        raise ValueError("Invalid monitoring sites API response")

    filepath = RAW_DIR / "monitoring_sites.json"
    save_json(data, filepath)

    print(f"Saved station metadata: {filepath}")


def extract_site_species():
    endpoint = "Information/MonitoringSiteSpecies/GroupName=London/Json"
    data = fetch_json(endpoint)

    if not isinstance(data, dict) or not isinstance(
        data.get("Sites"), dict
    ):
        raise ValueError("Invalid site-pollutant API response")

    filepath = RAW_DIR / "site_species.json"
    save_json(data, filepath)

    print(f"Saved site-pollutant metadata: {filepath}")


def extract_measurements(start_date, end_date, refresh=False):
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

            if filepath.exists() and not refresh:
                print(f"Already saved, skipping: {filename}")
                continue

            data = fetch_json(endpoint)

            # Validate before saving, so malformed API responses
            # are not stored as valid measurement snapshots.
            readings = validate_measurement_response(
                data, site_code, pollutant
            )

            if refresh:
                timestamp = datetime.now(timezone.utc).strftime(
                    "%Y%m%dT%H%M%S%fZ"
                )

                filename = (
                    f"{site_code}_{pollutant}_"
                    f"{start_date}_{end_date}_{timestamp}.json"
                )

                filepath = RAW_DIR / "measurements" / filename

            save_json(data, filepath)

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
        help="Start date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--end",
        default="2026-10-08",
        help="Exclusive end date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download new snapshots without overwriting originals",
    )

    args = parser.parse_args()

    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    except ValueError:
        parser.error(
            "Dates must be valid and use YYYY-MM-DD format"
        )

    if end_date <= start_date:
        parser.error("End date must be after start date")

    print("Starting AirLens extraction")
    print(f"Period: {start_date} to {end_date} (end exclusive)\n")

    extract_sites()
    extract_site_species()
    extract_measurements(start_date, end_date, args.refresh)

    print("\nExtraction complete")


if __name__ == "__main__":
    main()
