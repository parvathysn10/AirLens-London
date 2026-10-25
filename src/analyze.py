
from pathlib import Path

import duckdb

DB_PATH = Path("data/processed/airlens.duckdb")

START_DATE = "2026-10-01"
END_DATE = "2026-10-08"


def main():
    if not DB_PATH.exists():
        print("Database not found. Run python src/transform.py first.")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        query = """
            WITH station_readings AS (
                SELECT
                    s.site_code,
                    s.site_name,
                    s.site_type,
                    s.local_authority,
                    m.pollutant_code,
                    COUNT(*) AS returned_hours,
                    COUNT(m.value) AS valid_hours,
                    COUNT(*) - COUNT(m.value) AS missing_hours,
                    ROUND(AVG(m.value), 2) AS average_value
                FROM measurements m
                JOIN monitoring_sites s
                    ON m.site_code = s.site_code
                WHERE m.measured_at >= ?
                  AND m.measured_at < ?
                  AND m.pollutant_code = 'NO2'
                GROUP BY
                    s.site_code,
                    s.site_name,
                    s.site_type,
                    s.local_authority,
                    m.pollutant_code
            )
            SELECT
                *,
                ROUND(
                    valid_hours * 100.0 /
                    DATE_DIFF('hour', ?::TIMESTAMP, ?::TIMESTAMP),
                    1
                ) AS completeness_pct
            FROM station_readings
            ORDER BY completeness_pct DESC
        """

        results = con.execute(
            query,
            [START_DATE, END_DATE, START_DATE, END_DATE]
        ).fetchdf()

        print("\nAIRLENS - STATION COMPARISON")
        print(f"Period: {START_DATE} to {END_DATE} (end exclusive)")
        print("Pollutant: NO2\n")

        print(results.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    main()

