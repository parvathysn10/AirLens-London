
from pathlib import Path
import duckdb

DB_PATH = Path("data/processed/airlens.duckdb")

if not DB_PATH.exists():
    raise FileNotFoundError(f"Database not found: {DB_PATH}")

con = duckdb.connect(str(DB_PATH), read_only=True)

try:
    print("\n1. DUPLICATE MEASUREMENT KEYS")
    duplicates = con.execute("""
        SELECT
            site_code,
            pollutant_code,
            measured_at,
            COUNT(*) AS occurrences
        FROM measurements
        GROUP BY site_code, pollutant_code, measured_at
        HAVING COUNT(*) > 1
    """).fetchall()

    print(f"Duplicate keys: {len(duplicates)}")
    if duplicates:
        print("WARNING: Duplicate measurement keys found!")
        for row in duplicates[:10]:
            print(row)
    else:
        print("PASS: No duplicate measurement keys.")

    print("\n2. DATABASE HISTORY BY STATION")
    rows = con.execute("""
        SELECT
            site_code,
            MIN(measured_at) AS earliest,
            MAX(measured_at) AS latest,
            COUNT(*) AS stored_records,
            COUNT(value) AS valid_readings
        FROM measurements
        WHERE pollutant_code = 'NO2'
        GROUP BY site_code
        ORDER BY site_code
    """).fetchall()

    for row in rows:
        print(row)

    print("\n3. CHECK 8 OCTOBER WAS ALREADY STORED")
    rows = con.execute("""
        SELECT
            site_code,
            COUNT(*) AS stored_records,
            COUNT(value) AS valid_readings
        FROM measurements
        WHERE pollutant_code = 'NO2'
          AND measured_at >= TIMESTAMP '2026-10-08 00:00:00'
          AND measured_at < TIMESTAMP '2026-10-09 00:00:00'
        GROUP BY site_code
        ORDER BY site_code
    """).fetchall()

    if rows:
        for row in rows:
            print(row)
    else:
        print("No measurements found for 8 October.")

    print("\n4. TOTAL MEASUREMENT ROWS")
    total = con.execute(
        "SELECT COUNT(*) FROM measurements"
    ).fetchone()[0]

    print(f"Total rows: {total}")

finally:
    con.close()
