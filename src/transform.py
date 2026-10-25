
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw")
DB_PATH = Path("data/processed/airlens.duckdb")


def load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as file:
        return json.load(file)


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def parse_number(value):
    if value in ("", None):
        return None
    return float(value)


def create_tables(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_sites (
            site_code VARCHAR PRIMARY KEY,
            site_name VARCHAR,
            site_type VARCHAR,
            local_authority VARCHAR,
            latitude DOUBLE,
            longitude DOUBLE,
            date_opened DATE,
            date_closed DATE
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS site_pollutants (
            site_code VARCHAR,
            pollutant_code VARCHAR,
            pollutant_name VARCHAR,
            date_started DATE,
            date_finished DATE,
            PRIMARY KEY (site_code, pollutant_code)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            site_code VARCHAR,
            pollutant_code VARCHAR,
            measured_at TIMESTAMP,
            value DOUBLE,
            PRIMARY KEY (site_code, pollutant_code, measured_at)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            run_id VARCHAR PRIMARY KEY,
            started_at TIMESTAMP,
            inserted INTEGER,
            updated INTEGER,
            unchanged INTEGER,
            rejected INTEGER
        )
    """)


def load_sites(con):
    data = load_json(RAW_DIR / "monitoring_sites.json")
    sites = as_list(data["Sites"]["Site"])

    for site in sites:
        con.execute("""
            INSERT INTO monitoring_sites
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (site_code) DO UPDATE SET
                site_name = EXCLUDED.site_name,
                site_type = EXCLUDED.site_type,
                local_authority = EXCLUDED.local_authority,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                date_opened = EXCLUDED.date_opened,
                date_closed = EXCLUDED.date_closed
        """, [
            site["@SiteCode"],
            site.get("@SiteName"),
            site.get("@SiteType"),
            site.get("@LocalAuthorityName"),
            parse_number(site.get("@Latitude")),
            parse_number(site.get("@Longitude")),
            parse_date(site.get("@DateOpened")),
            parse_date(site.get("@DateClosed"))
        ])

    print(f"Loaded {len(sites)} monitoring sites")


def load_site_pollutants(con):
    data = load_json(RAW_DIR / "site_species.json")
    sites = as_list(data["Sites"]["Site"])

    count = 0

    for site in sites:
        for pollutant in as_list(site.get("Species")):
            con.execute("""
                INSERT INTO site_pollutants
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (site_code, pollutant_code)
                DO UPDATE SET
                    pollutant_name = EXCLUDED.pollutant_name,
                    date_started = EXCLUDED.date_started,
                    date_finished = EXCLUDED.date_finished
            """, [
                site["@SiteCode"],
                pollutant["@SpeciesCode"],
                pollutant.get("@SpeciesDescription"),
                parse_date(pollutant.get("@DateMeasurementStarted")),
                parse_date(pollutant.get("@DateMeasurementFinished"))
            ])
            count += 1

    print(f"Loaded {count} site-pollutant records")


def measurement_files():
    files = list((RAW_DIR / "measurements").glob("*.json"))

    # Original files have no download timestamp in their names
    def snapshot_order(filepath):
        parts = filepath.stem.split("_")
        snapshot_time = parts[4] if len(parts) > 4 else ""
        return (snapshot_time, filepath.name)

    return sorted(files, key=snapshot_order)


def load_measurements(con):
    counts = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0
    }

    for filepath in measurement_files():
        data = load_json(filepath)
        raw = data["RawAQData"]

        site_code = raw["@SiteCode"]
        pollutant_code = raw["@SpeciesCode"]

        for reading in as_list(raw.get("Data")):
            try:
                timestamp = reading["@MeasurementDateGMT"]
                measured_at = datetime.strptime(
                    timestamp, "%Y-%m-%d %H:%M:%S"
                )
                value = parse_number(reading.get("@Value"))

            except (KeyError, ValueError, TypeError):
                counts["rejected"] += 1
                continue

            existing = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = ?
                  AND pollutant_code = ?
                  AND measured_at = ?
            """, [
                site_code, pollutant_code, measured_at
            ]).fetchone()

            if existing is None:
                con.execute("""
                    INSERT INTO measurements
                    VALUES (?, ?, ?, ?)
                """, [
                    site_code, pollutant_code, measured_at, value
                ])
                counts["inserted"] += 1

            elif existing[0] == value or (
                existing[0] is None and value is None
            ):
                counts["unchanged"] += 1

            else:
                con.execute("""
                    UPDATE measurements
                    SET value = ?
                    WHERE site_code = ?
                      AND pollutant_code = ?
                      AND measured_at = ?
                """, [
                    value, site_code, pollutant_code, measured_at
                ])
                counts["updated"] += 1

    return counts


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%S%fZ")

    con = duckdb.connect(str(DB_PATH))

    try:
        con.execute("BEGIN TRANSACTION")

        create_tables(con)
        load_sites(con)
        load_site_pollutants(con)

        counts = load_measurements(con)

        con.execute("""
            INSERT INTO ingestion_runs
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            run_id,
            started_at.replace(tzinfo=None),
            counts["inserted"],
            counts["updated"],
            counts["unchanged"],
            counts["rejected"]
        ])

        con.execute("COMMIT")

        print("\nINGESTION SUMMARY")
        for name, count in counts.items():
            print(f"{name.capitalize()}: {count}")

        print("\nDATABASE SUMMARY")
        for table in [
            "monitoring_sites",
            "site_pollutants",
            "measurements",
            "ingestion_runs"
        ]:
            count = con.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            print(f"{table}: {count} rows")

    except Exception:
        con.execute("ROLLBACK")
        raise

    finally:
        con.close()


if __name__ == "__main__":
    main()

