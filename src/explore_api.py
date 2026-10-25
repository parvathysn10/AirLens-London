
import requests
from collections import Counter

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"

def fetch_json(endpoint):
    url = f"{BASE_URL}/{endpoint}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


# Explore monitoring stations
site_data = fetch_json(
    "Information/MonitoringSites/GroupName=London/Json"
)

sites = site_data["Sites"]["Site"]

active_sites = [
    site for site in sites
    if not site.get("@DateClosed")
]

closed_sites = [
    site for site in sites
    if site.get("@DateClosed")
]

print("MONITORING STATIONS")
print("Total stations:", len(sites))
print("Potentially active stations:", len(active_sites))
print("Closed stations:", len(closed_sites))

# Check the types of potentially active stations
site_types = Counter(
    site.get("@SiteType", "Unknown")
    for site in active_sites
)

print("\nPOTENTIALLY ACTIVE STATIONS BY TYPE")

for site_type, count in sorted(site_types.items()):
    print(f"{site_type}: {count}")

# Explore which pollutants are monitored at each station
species_data = fetch_json(
    "Information/MonitoringSiteSpecies/GroupName=London/Json"
)

print("\nSITE-POLLUTANT RESPONSE STRUCTURE")
print("Top-level keys:", list(species_data.keys()))
print("Response preview:", str(species_data)[:2000])

# Examine pollutant coverage at potentially active stations
site_species = species_data["Sites"]["Site"]

pollutant_counts = Counter()
pollutant_sites = {}

for site in site_species:
    if site.get("@DateClosed"):
        continue

    species = site.get("Species", [])

    # The API can return either one pollutant or a list
    if isinstance(species, dict):
        species = [species]

    for pollutant in species:
        if pollutant.get("@DateMeasurementFinished"):
            continue

        code = pollutant.get("@SpeciesCode")

        if not code:
            continue

        pollutant_counts[code] += 1

        pollutant_sites.setdefault(code, []).append(
            {
                "site_code": site["@SiteCode"],
                "site_name": site["@SiteName"],
                "site_type": site.get("@SiteType")
            }
        )

print("\nPOLLUTANTS AT POTENTIALLY ACTIVE STATIONS")

for code, count in pollutant_counts.most_common():
    print(f"{code}: {count} stations")

print("\nEXAMPLE NO2 STATIONS")

for site in pollutant_sites.get("NO2", [])[:10]:
    print(
        site["site_code"],
        "|",
        site["site_name"],
        "|",
        site["site_type"]
    )
