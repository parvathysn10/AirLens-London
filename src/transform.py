
import hashlib
import json
import math
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

    number = float(value)

    if not math.isfinite(number):
        raise ValueError("Value must be a finite number")

    return number


def snapshot_priority(filepath):
    """
    Return a sortable priority for a raw measurement snapshot.

    Original files have no download timestamp and rank first.
    Refreshed files have a UTC download timestamp in their filename.

    Example:
    BL0_NO2_2026-10-24_2026-10-27_20261026T225704072037Z.json
    """
    parts = filepath.stem.split("_")

    snapshot_time = (
        parts[4]
        if len(parts) > 4
        else ""
    )

    return (snapshot_time, filepath.name)


def measurement_files():
    files = list((RAW_DIR / "measurements").glob("*.json"))
    return sorted(files, key=snapshot_priority)


def file_hash(filepath):
    return hashlib.sha256(filepath.read_bytes()).hexdigest()


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

    con.execute("""
        CREATE TABLE IF NOT EXISTS processed_snapshots (
            filepath VARCHAR PRIMARY KEY,
            file_hash VARCHAR,
            processed_at TIMESTAMP
        )
    """)

    # Compatible with an existing database.
    con.execute("""
        ALTER TABLE measurements
        ADD COLUMN IF NOT EXISTS source_snapshot VARCHAR
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


def read_snapshot(filepath):
    """
    Parse one raw JSON snapshot into measurement records.
    Invalid readings are counted and skipped.
    """
    data = load_json(filepath)
    raw = data["RawAQData"]

    site_code = raw["@SiteCode"]
    pollutant_code = raw["@SpeciesCode"]

    records = []
    rejected = 0

    for reading in as_list(raw.get("Data")):
        try:
            timestamp = reading["@MeasurementDateGMT"]

            measured_at = datetime.strptime(
                timestamp, "%Y-%m-%d %H:%M:%S"
            )

            value = parse_number(reading.get("@Value"))

        except (KeyError, ValueError, TypeError):
            rejected += 1
            continue

        records.append((
            site_code,
            pollutant_code,
            measured_at,
            value
        ))

    return records, rejected


def migrate_existing_sources(con, files):
    """
    Initialize source_snapshot for measurements already in DuckDB.

    Existing rows were loaded before source tracking existed.
    Reconstruct their latest matching source from saved snapshots.

    Only assign a source when the saved snapshot value matches
    the value currently stored in DuckDB.

    This does not change any measurement values.
    """
    missing = con.execute("""
        SELECT COUNT(*)
        FROM measurements
        WHERE source_snapshot IS NULL
    """).fetchone()[0]

    if missing == 0:
        return

    print(
        f"\nInitializing snapshot sources for "
        f"{missing} existing measurements..."
    )

    assigned = 0

    # Newest snapshots first.
    for filepath in reversed(files):
        relative_path = filepath.as_posix()
        records, _ = read_snapshot(filepath)

        for site_code, pollutant_code, measured_at, value in records:
            result = con.execute("""
                UPDATE measurements
                SET source_snapshot = ?
                WHERE site_code = ?
                  AND pollutant_code = ?
                  AND measured_at = ?
                  AND source_snapshot IS NULL
                  AND value IS NOT DISTINCT FROM ?
            """, [
                relative_path,
                site_code,
                pollutant_code,
                measured_at,
                value
            ])

            # DuckDB returns a count for UPDATE statements.
            assigned += result.fetchone()[0]

    remaining = con.execute("""
        SELECT COUNT(*)
        FROM measurements
        WHERE source_snapshot IS NULL
    """).fetchone()[0]

    print(f"Source snapshots assigned: {assigned}")
    print(f"Measurements without a matching source: {remaining}")

    if remaining:
        raise RuntimeError(
            "Some existing measurements could not be matched to "
            "their saved raw snapshots. No changes have been committed. "
            "Check the raw files before continuing."
        )


def load_measurements(con):
    counts = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0
    }

    processed_files = 0
    skipped_files = 0
    older_readings_ignored = 0

    files = measurement_files()

    # One-time migration for measurements loaded before source tracking.
    migrate_existing_sources(con, files)

    for filepath in files:
        relative_path = filepath.as_posix()
        current_hash = file_hash(filepath)

        previous = con.execute("""
            SELECT file_hash
            FROM processed_snapshots
            WHERE filepath = ?
        """, [relative_path]).fetchone()

        if previous is not None and previous[0] == current_hash:
            skipped_files += 1
            continue

        records, rejected = read_snapshot(filepath)
        counts["rejected"] += rejected

        for site_code, pollutant_code, measured_at, value in records:
            existing = con.execute("""
                SELECT value, source_snapshot
                FROM measurements
                WHERE site_code = ?
                  AND pollutant_code = ?
                  AND measured_at = ?
            """, [
                site_code,
                pollutant_code,
                measured_at
            ]).fetchone()

            if existing is None:
                con.execute("""
                    INSERT INTO measurements (
                        site_code,
                        pollutant_code,
                        measured_at,
                        value,
                        source_snapshot
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, [
                    site_code,
                    pollutant_code,
                    measured_at,
                    value,
                    relative_path
                ])

                counts["inserted"] += 1
                continue

            old_value, old_source = existing

            # A newer source must always take priority.
            if old_source is not None:
                old_priority = snapshot_priority(Path(old_source))
                new_priority = snapshot_priority(filepath)

                if new_priority < old_priority:
                    older_readings_ignored += 1
                    continue

            same_value = (
                old_value == value
                or (old_value is None and value is None)
            )

            if same_value:
                counts["unchanged"] += 1

                # Even if the value is identical, remember the
                # newer source so an older file cannot later
                # overwrite this measurement.
                if old_source != relative_path:
                    con.execute("""
                        UPDATE measurements
                        SET source_snapshot = ?
                        WHERE site_code = ?
                          AND pollutant_code = ?
                          AND measured_at = ?
                    """, [
                        relative_path,
                        site_code,
                        pollutant_code,
                        measured_at
                    ])

            else:
                con.execute("""
                    UPDATE measurements
                    SET value = ?,
                        source_snapshot = ?
                    WHERE site_code = ?
                      AND pollutant_code = ?
                      AND measured_at = ?
                """, [
                    value,
                    relative_path,
                    site_code,
                    pollutant_code,
                    measured_at
                ])

                counts["updated"] += 1

        con.execute("""
            INSERT INTO processed_snapshots
            VALUES (?, ?, ?)
            ON CONFLICT (filepath) DO UPDATE SET
                file_hash = EXCLUDED.file_hash,
                processed_at = EXCLUDED.processed_at
        """, [
            relative_path,
            current_hash,
            datetime.now(timezone.utc).replace(tzinfo=None)
        ])

        processed_files += 1

    print("\nSNAPSHOT SUMMARY")
    print(f"Processed files: {processed_files}")
    print(f"Skipped unchanged files: {skipped_files}")
    print(f"Older readings ignored: {older_readings_ignored}")

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
            "ingestion_runs",
            "processed_snapshots"
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
