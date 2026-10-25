
import tempfile
from pathlib import Path

import duckdb


def main():
    with tempfile.TemporaryDirectory() as folder:
        db_path = Path(folder) / "test.duckdb"
        con = duckdb.connect(str(db_path))

        try:
            con.execute("""
                CREATE TABLE measurements (
                    site_code VARCHAR,
                    pollutant_code VARCHAR,
                    measured_at TIMESTAMP,
                    value DOUBLE,
                    PRIMARY KEY (site_code, pollutant_code, measured_at)
                )
            """)

            con.execute("""
                INSERT INTO measurements
                VALUES ('BT8', 'NO2', '2026-10-01 00:00:00', 18.5)
            """)

            incoming_value = 21.0

            existing = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'BT8'
                  AND pollutant_code = 'NO2'
                  AND measured_at = '2026-10-01 00:00:00'
            """).fetchone()

            if existing is None:
                print("New measurement")
            elif existing[0] == incoming_value:
                print("Unchanged measurement")
            else:
                con.execute("""
                    UPDATE measurements
                    SET value = ?
                    WHERE site_code = 'BT8'
                      AND pollutant_code = 'NO2'
                      AND measured_at = '2026-10-01 00:00:00'
                """, [incoming_value])

                print("Updated existing measurement")

            result = con.execute("""
                SELECT value
                FROM measurements
                WHERE site_code = 'BT8'
                  AND pollutant_code = 'NO2'
                  AND measured_at = '2026-10-01 00:00:00'
            """).fetchone()[0]

            count = con.execute("""
                SELECT COUNT(*) FROM measurements
            """).fetchone()[0]

            assert result == 21.0
            assert count == 1

            print(f"Stored value: {result}")
            print(f"Measurement rows: {count}")
            print("Measurement update test passed")

        finally:
            con.close()


if __name__ == "__main__":
    main()
