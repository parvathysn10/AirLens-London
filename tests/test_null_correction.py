
import tempfile
from pathlib import Path

from unittest.mock import patch

import duckdb

from src import transform
from tests.test_snapshot_protection import make_snapshot


def test_newer_missing_value_replaces_older_value():
    # Create an isolated directory for synthetic API snapshots.
    # No real downloaded measurements are modified.
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)

        # Simulate an earlier snapshot containing a valid numeric reading.
        older = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T100000000000Z.json",
            10.0,
        )

        # Simulate a later download correcting that reading to missing.
        # An empty string represents a missing value in the raw API data.
        newer = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T120000000000Z.json",
            "",
        )

        # Use an in-memory DuckDB database to avoid changing project data.
        con = duckdb.connect(":memory:")

        try:
            # Create the same database schema used by the ingestion pipeline.
            transform.create_tables(con)

            # Replace filesystem discovery with the two controlled snapshots.
            # This tests the real ingestion logic without relying on live API data.
            with patch.object(
                transform,
                "measurement_files",
                return_value=[older, newer],
            ):
                transform.load_measurements(con)

            # Retrieve the measurement after both snapshots are processed.
            result = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'TEST'
            """).fetchone()

            # The measurement must exist, but its corrected value must be NULL.
            # This verifies that newer missing data replaces the older value.
            assert result is not None
            assert result[0] is None

        finally:
            # Close the temporary database connection after testing.
            con.close()
