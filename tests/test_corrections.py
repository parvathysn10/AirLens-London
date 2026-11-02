
from pathlib import Path

import duckdb

# Use the existing AirLens London database for a transaction rollback test.
DB_PATH = Path("data/processed/airlens.duckdb")


def main():
    con = duckdb.connect(str(DB_PATH))

    try:
        # Select a known historical measurement to test.
        # The original value will be compared against the restored value.
        original = con.execute("""
            SELECT value
            FROM measurements
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """).fetchone()

        # A valid numeric reading is required for the temporary update.
        if original is None or original[0] is None:
            print("Test measurement not found or has no value.")
            return

        print(f"Original value: {original[0]}")

        # Begin a transaction so the temporary change can be reversed.
        con.execute("BEGIN TRANSACTION")

        # Simulate an incorrect measurement update by adding 100.
        # This change is not committed to the database.
        con.execute("""
            UPDATE measurements
            SET value = value + 100
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """)

        # Confirm that the updated value is visible within the transaction.
        changed = con.execute("""
            SELECT value
            FROM measurements
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """).fetchone()[0]

        print(f"Temporarily changed value: {changed}")

        # Discard the uncommitted change and restore the original state.
        con.execute("ROLLBACK")

        # Read the measurement again after the transaction is rolled back.
        restored = con.execute("""
            SELECT value
            FROM measurements
            WHERE site_code = 'BT8'
              AND pollutant_code = 'NO2'
              AND measured_at = '2026-10-01 00:00:00'
        """).fetchone()[0]

        print(f"Value after rollback: {restored}")

        # Verify that the database value matches its original value.
        assert restored == original[0]
        print("Rollback test passed")

    finally:
        # Close the database connection even if the test fails.
        con.close()


if __name__ == "__main__":
    main()
