
import argparse
from datetime import date
from pathlib import Path

import duckdb

DB_PATH = Path("data/processed/airlens.duckdb")


def main():
    parser = argparse.ArgumentParser(
        description="Analyse historical London air quality measurements"
    )

    parser.add_argument(
        "--start",
        default="2026-10-01",
        help="Start date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--end",
        default="2026-10-08",
        help="Exclusive end date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--pollutant",
        default="NO2",
        help="Pollutant code to analyse",
    )

    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    pollutant = args.pollutant.upper()

    if end_date <= start_date:
        parser.error("End date must be after start date")

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
                  AND m.pollutant_code = ?
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
            [
                start_date,
                end_date,
                pollutant,
                start_date,
                end_date,
            ],
        ).fetchdf()

        print("\nAIRLENS - STATION COMPARISON")
        print(f"Period: {start_date} to {end_date} (end exclusive)")
        print(f"Pollutant: {pollutant}\n")

        if results.empty:
            print("No measurements found for the selected period.")
        else:
            print(results.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    main()
