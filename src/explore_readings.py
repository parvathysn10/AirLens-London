
import requests

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"

site_code = "BL0"
species_code = "NO2"
start_date = "2026-10-01"
end_date = "2026-10-08"

endpoint = (
    f"Data/SiteSpecies/SiteCode={site_code}/"
    f"SpeciesCode={species_code}/"
    f"StartDate={start_date}/EndDate={end_date}/Json"
)

url = f"{BASE_URL}/{endpoint}"

print("Request URL:", url)

response = requests.get(url, timeout=60)

print("HTTP status:", response.status_code)
response.raise_for_status()

data = response.json()

print("\nTop-level keys:", list(data.keys()))
print("\nResponse preview:")
print(str(data)[:2500])

# Inspect the completeness of the returned measurements
readings = data["RawAQData"]["Data"]

total_readings = len(readings)

missing_readings = sum(
    1 for reading in readings
    if reading.get("@Value") in ("", None)
)

valid_readings = total_readings - missing_readings

completeness = (
    valid_readings / total_readings * 100
    if total_readings else 0
)

print("\nMEASUREMENT QUALITY")
print("Total returned readings:", total_readings)
print("Valid readings:", valid_readings)
print("Missing readings:", missing_readings)
print(f"Completeness of returned readings: {completeness:.1f}%")

print("\nFIRST AND LAST TIMESTAMPS")
if readings:
    print("First:", readings[0]["@MeasurementDateGMT"])
    print("Last:", readings[-1]["@MeasurementDateGMT"])
