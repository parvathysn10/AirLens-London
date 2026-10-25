
import requests
from datetime import datetime

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"

START_DATE = "2026-10-01"
END_DATE = "2026-10-08"

stations = {
    "BL0": "Camden - Bloomsbury",
    "BG1": "Barking and Dagenham - Rush Green",
    "BQ7": "Bexley - Belvedere West",
    "BT8": "Brent - ARK Franklin Primary Academy",
}

species_code = "NO2"

start = datetime.strptime(START_DATE, "%Y-%m-%d")
end = datetime.strptime(END_DATE, "%Y-%m-%d")
expected_hours = int((end - start).total_seconds() / 3600)

print(f"Expected hours: {expected_hours}")
print(f"Pollutant: {species_code}\n")

for site_code, site_name in stations.items():
    endpoint = (
        f"Data/SiteSpecies/SiteCode={site_code}/"
        f"SpeciesCode={species_code}/"
        f"StartDate={START_DATE}/EndDate={END_DATE}/Json"
    )

    try:
        response = requests.get(
            f"{BASE_URL}/{endpoint}",
            timeout=60
        )
        response.raise_for_status()

        data = response.json()
        readings = data["RawAQData"].get("Data", [])

        if isinstance(readings, dict):
            readings = [readings]

        valid_timestamps = set()

        for reading in readings:
            timestamp = reading.get("@MeasurementDateGMT")
            value = reading.get("@Value")

            if not timestamp or value in ("", None):
                continue

            reading_time = datetime.strptime(
                timestamp, "%Y-%m-%d %H:%M:%S"
            )

            if start <= reading_time < end:
                valid_timestamps.add(reading_time)

        completeness = (
            len(valid_timestamps) / expected_hours * 100
        )

        print(f"{site_name} ({site_code})")
        print(f"  Returned rows: {len(readings)}")
        print(f"  Valid unique hours: {len(valid_timestamps)}")
        print(f"  Completeness: {completeness:.1f}%\n")

    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        print(f"{site_name} ({site_code})")
        print(f"  Error: {error}\n")
