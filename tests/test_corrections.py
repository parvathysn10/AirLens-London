
from pathlib import Path

import duckdb

DB_PATH = Path("data/processed/airlens.duckdb")


def main():
    con = duckdb.connect(str(DB_PATH))

    try:
        original = con.execute("""
            SELECT value
            FROM measurements
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """).fetchone()

        if original is None or original[0] is None:
            print("Test measurement not found or has no value.")
            return

        print(f"Original value: {original[0]}")

        con.execute("BEGIN TRANSACTION")

        con.execute("""
            UPDATE measurements
            SET value = value + 100
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """)

        changed = con.execute("""
            SELECT value
            FROM measurements
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """).fetchone()[0]

        print(f"Temporarily changed value: {changed}")

        con.execute("ROLLBACK")

        restored = con.execute("""
            SELECT value
            FROM measurements
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """).fetchone()[0]

        print(f"Value after rollback: {restored}")

        assert restored == original[0]
        print("Rollback test passed")

    finally:
        con.close()


if __name__ == "__main__":
    main()
