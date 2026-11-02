
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import duckdb

from src import transform


# Create synthetic measurement snapshots with controlled values and filenames.
# This allows ingestion behaviour to be tested without API requests.
def make_snapshot(folder, filename, value):
    filepath = folder / filename

    data = {
        "RawAQData": {
            "@SiteCode": "TEST",
            "@SpeciesCode": "NO2",
            "Data": {
                "@MeasurementDateGMT": "2026-10-24 12:00:00",
                "@Value": str(value)
            }
        }
    }

    filepath.write_text(json.dumps(data), encoding="utf-8")
    return filepath


# Verify that newer measurement snapshots always take precedence.
def test_snapshot_protection():
    # Use temporary files so the test does not affect real project data.
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)

        # Earlier download: the measurement initially has a value of 10.
        older = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T100000000000Z.json",
            10.0
        )

        # Later download: the same measurement has been corrected to 20.
        newer = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T120000000000Z.json",
            20.0
        )

        # Use an in-memory database to isolate the test from stored data.
        con = duckdb.connect(":memory:")

        try:
            transform.create_tables(con)

            # Process both snapshots using the real ingestion function.
            # The newer snapshot should determine the stored value.
            with patch.object(
                transform,
                "measurement_files",
                return_value=[older, newer]
            ):
                transform.load_measurements(con)

            first_value = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'TEST'
            """).fetchone()[0]

            assert first_value == 20.0

            # Modify the older file after the newer one was processed.
            # Its changed contents will produce a different file hash.
            make_snapshot(folder, older.name, 99.0)

            # Reprocess the snapshots to check that an older source
            # cannot overwrite the value from a newer source.
            with patch.object(
                transform,
                "measurement_files",
                return_value=[older, newer]
            ):
                transform.load_measurements(con)

            final_value = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'TEST'
            """).fetchone()[0]

            # The corrected value must remain 20, not the older file's 99.
            assert final_value == 20.0, (
                "An older snapshot overwrote the newer measurement"
            )

            print("Snapshot protection test passed")

        finally:
            # Release the database connection after testing.
            con.close()


if __name__ == "__main__":
    test_snapshot_protection()
