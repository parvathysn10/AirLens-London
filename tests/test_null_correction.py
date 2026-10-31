import tempfile
from pathlib import Path

from unittest.mock import patch

import duckdb

from src import transform
from tests.test_snapshot_protection import make_snapshot


def test_newer_missing_value_replaces_older_value():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)

        older = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T100000000000Z.json",
            10.0,
        )

        newer = make_snapshot(
            folder,
            "TEST_NO2_2026-10-24_2026-10-27_20261026T120000000000Z.json",
            "",
        )

        con = duckdb.connect(":memory:")

        try:
            transform.create_tables(con)

            with patch.object(
                transform,
                "measurement_files",
                return_value=[older, newer],
            ):
                transform.load_measurements(con)

            result = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'TEST'
            """).fetchone()

            assert result is not None
            assert result[0] is None

        finally:
            con.close()