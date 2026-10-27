
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import duckdb

from src import transform


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


def test_snapshot_protection():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)

        older = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T100000000000Z.json",
            10.0
        )

        newer = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T120000000000Z.json",
            20.0
        )

        con = duckdb.connect(":memory:")

        try:
            transform.create_tables(con)

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
            make_snapshot(folder, older.name, 99.0)

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

            assert final_value == 20.0, (
                "An older snapshot overwrote the newer measurement"
            )

            print("Snapshot protection test passed")

        finally:
            con.close()


if __name__ == "__main__":
    test_snapshot_protection()
