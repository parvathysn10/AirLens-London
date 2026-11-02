
import tempfile
from pathlib import Path

import duckdb


def main():
    # Create an isolated temporary database for testing.
    # The temporary directory is automatically removed afterwards.
    with tempfile.TemporaryDirectory() as folder:
        db_path = Path(folder) / "test.duckdb"
        con = duckdb.connect(str(db_path))

        try:
            # Reproduce the composite primary key used in the main
            # measurements table to prevent duplicate hourly records.
            con.execute("""
                CREATE TABLE measurements (
                    site_code VARCHAR,
                    pollutant_code VARCHAR,
                    measured_at TIMESTAMP,
                    value DOUBLE,
                    PRIMARY KEY (site_code, pollutant_code, measured_at)
                )
            """)

            # Insert an initial hourly NO2 measurement for station BT8.
            con.execute("""
                INSERT INTO measurements
                VALUES ('BT8', 'NO2', '2026-10-01 00:00:00', 18.5)
            """)

            # Simulate receiving a corrected value for the same measurement.
            incoming_value = 21.0

            # Check whether the station, pollutant and timestamp already exist.
            existing = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'BT8'
                  AND pollutant_code = 'NO2'
                  AND measured_at = '2026-10-01 00:00:00'
            """).fetchone()

            # Classify the incoming reading as new, unchanged or corrected.
            if existing is None:
                print("New measurement")
            elif existing[0] == incoming_value:
                print("Unchanged measurement")
            else:
                # Update the existing row rather than inserting a duplicate.
                con.execute("""
                    UPDATE measurements
                    SET value = ?
                    WHERE site_code = 'BT8'
                      AND pollutant_code = 'NO2'
                      AND measured_at = '2026-10-01 00:00:00'
                """, [incoming_value])

                print("Updated existing measurement")

            # Read the stored measurement after processing the correction.
            result = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'BT8'
                  AND pollutant_code = 'NO2'
                  AND measured_at = '2026-10-01 00:00:00'
            """).fetchone()[0]

            # Confirm that the update has not increased the row count.
            count = con.execute("""
                SELECT COUNT(*) FROM measurements
            """).fetchone()[0]

            # Both conditions must hold for the update test to pass.
            assert result == 21.0
            assert count == 1

            print(f"Stored value: {result}")
            print(f"Measurement rows: {count}")
            print("Measurement update test passed")

        finally:
            # Release the connection before deleting the temporary database.
            con.close()


if __name__ == "__main__":
    main()
