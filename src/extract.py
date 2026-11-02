
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# API configuration and local storage for raw responses.
BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"
RAW_DIR = Path("data/raw")

# Selected monitoring locations across different London environments.
STATIONS = {
    "BL0": "Camden - Bloomsbury",
    "BG1": "Barking and Dagenham - Rush Green",
    "BQ7": "Bexley - Belvedere West",
    "BT8": "Brent - ARK Franklin Primary Academy",
    "RI2": "Richmond Upon Thames - Barnes Wetlands",
    "LB6": "Lambeth - Streatham Green",
}

# Pollutants requested for each station.
POLLUTANTS = ["NO2", "PM25", "PM10"]


# HTTP requests and error handling.
def fetch_json(endpoint):
    """Fetch JSON from LAQN, retrying temporary network/server failures."""
    url = f"{BASE_URL}/{endpoint}"

    # Retry rate limits and temporary server failures.
    # Backoff reduces repeated requests while the service is struggling.
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    try:
        with requests.Session() as session:
            session.mount(
                "https://",
                HTTPAdapter(max_retries=retry_strategy),
            )

            # Avoid indefinitely waiting for an unresponsive endpoint.
            # Surface unsuccessful HTTP responses instead of silently continuing.
            response = session.get(url, timeout=60)
            response.raise_for_status()
            return response.json()

    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(
            f"Failed to fetch LAQN data from {url}: {error}"
        ) from error


# Measurement response validation.
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

    # Reject responses that do not match the requested station or pollutant.
    if raw.get("@SiteCode") != site_code:
        raise ValueError(
            f"Unexpected station code in API response: {site_code}"
        )

    if raw.get("@SpeciesCode") != pollutant:
        raise ValueError(
            f"Unexpected pollutant code in API response: {pollutant}"
        )

    readings = raw.get("Data")

    # No available measurements is different from a malformed API response.
    if readings is None:
        return []

    # The API may return one reading as an object or several as a list.
    # Normalise both cases to a list for consistent downstream processing.
    if isinstance(readings, dict):
        return [readings]

    if isinstance(readings, list):
        return readings

    raise ValueError(
        f"Invalid measurements for {site_code}/{pollutant}: "
        "Data must be a list, object or null"
    )


# Raw JSON storage.
def save_json(data, filepath):
    """Save an API response as a JSON file."""
    # Preserve the original response so it can be inspected or reprocessed.
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


# Monitoring-site metadata extraction.
def extract_sites():
    """Download London monitoring station metadata."""
    endpoint = "Information/MonitoringSites/GroupName=London/Json"
    data = fetch_json(endpoint)

    if not isinstance(data, dict) or not isinstance(
        data.get("Sites"), dict
    ):
        raise ValueError("Invalid monitoring sites API response")

    filepath = RAW_DIR / "monitoring_sites.json"
    save_json(data, filepath)

    print(f"Saved station metadata: {filepath}")


# Site-pollutant metadata extraction.
def extract_site_species():
    """Download information about which pollutants stations monitor."""
    endpoint = "Information/MonitoringSiteSpecies/GroupName=London/Json"
    data = fetch_json(endpoint)

    if not isinstance(data, dict) or not isinstance(
        data.get("Sites"), dict
    ):
        raise ValueError("Invalid site-pollutant API response")

    filepath = RAW_DIR / "site_species.json"
    save_json(data, filepath)

    print(f"Saved site-pollutant metadata: {filepath}")


# Hourly measurement extraction and snapshot management.
def extract_measurements(start_date, end_date, refresh=False):
    """Download hourly measurements for each station and pollutant."""
    # Request all 18 station-pollutant combinations (6 stations x 3 pollutants).
    for site_code, site_name in STATIONS.items():
        for pollutant in POLLUTANTS:
            endpoint = (
                f"Data/SiteSpecies/SiteCode={site_code}/"
                f"SpeciesCode={pollutant}/"
                f"StartDate={start_date}/EndDate={end_date}/Json"
            )

            # Identify each snapshot by its station, pollutant and date range.
            filename = (
                f"{site_code}_{pollutant}_"
                f"{start_date}_{end_date}.json"
            )

            filepath = RAW_DIR / "measurements" / filename

            # Reuse existing snapshots unless fresh data is requested.
            # This avoids unnecessary API calls during historical reprocessing.
            if filepath.exists() and not refresh:
                print(f"Already saved, skipping: {filename}")
                continue

            data = fetch_json(endpoint)

            # Validate before saving, so malformed API responses
            # are not stored as valid measurement snapshots.
            readings = validate_measurement_response(
                data, site_code, pollutant
            )

            # Refreshes create timestamped copies rather than overwriting
            # earlier snapshots, preserving the history of API responses.
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


# Command-line configuration and extraction workflow.
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

    # Validate the date range before making any API requests.
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

    # Collect metadata and measurements for the requested period.
    extract_sites()
    extract_site_species()
    extract_measurements(start_date, end_date, args.refresh)

    print("\nExtraction complete")


if __name__ == "__main__":
    main()
