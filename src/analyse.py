
import argparse
from datetime import date
from pathlib import Path

import duckdb


DB_PATH = Path("data/processed/airlens.duckdb")


def analyse_stations(con, start_date, end_date, pollutant):
    """
    Compare station measurements over a selected date range.

    Completeness is the percentage of expected hourly readings
    that contain a valid numerical measurement.
    """

    # Join measurements to station metadata so results include names and locations.
    # COUNT(*) includes missing readings, but COUNT(m.value) ignores NULL values.
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
            DATE_DIFF(
                'hour',
                ?::TIMESTAMP,
                ?::TIMESTAMP
            ) AS expected_hours,
            ROUND(
                valid_hours * 100.0 /
                NULLIF(
                    DATE_DIFF(
                        'hour',
                        ?::TIMESTAMP,
                        ?::TIMESTAMP
                    ),
                    0
                ),
                1
            ) AS completeness_pct
        FROM station_readings
        ORDER BY
            completeness_pct DESC,
            site_name ASC
    """

    # Question marks safely insert the dates and pollutant into the SQL query.
    # fetchdf() returns the results as a pandas DataFrame.
    return con.execute(
        query,
        [
            start_date,
            end_date,
            pollutant,
            start_date,
            end_date,
            start_date,
            end_date,
        ],
    ).fetchdf()


def main():
    # Read the date range and pollutant from the command line.
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

    # Check the dates before querying the database.
    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    except ValueError:
        parser.error(
            "Dates must be valid and use YYYY-MM-DD format"
        )

    if end_date <= start_date:
        parser.error("End date must be after start date")

    pollutant = args.pollutant.strip().upper()

    if not pollutant:
        parser.error("Pollutant code cannot be empty")

    if not DB_PATH.exists():
        parser.error(
            "Database not found. Run python src/transform.py first."
        )

    # Open DuckDB in read-only mode because analysis should not change stored data.
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        results = analyse_stations(
            con,
            start_date,
            end_date,
            pollutant,
        )

        print("\nAIRLENS - STATION COMPARISON")
        print(f"Period: {start_date} to {end_date} (end exclusive)")
        print(f"Pollutant: {pollutant}")
        print(
            f"Expected hourly readings per station: "
            f"{(end_date - start_date).days * 24}\n"
        )

        if results.empty:
            print("No measurements found for the selected period.")
        else:
            print(results.to_string(index=False))

            # Highlight stations that have no valid readings in the period.
            stations_without_valid_data = results[
                results["valid_hours"] == 0
            ]

            if not stations_without_valid_data.empty:
                print(
                    "\nNote: Some stations have no valid "
                    "measurements in this period."
                )

            print(
                "\nCompleteness = valid hourly readings / "
                "expected hourly readings x 100."
            )
            print(
                "Average values exclude missing measurements."
            )

    finally:
        con.close()


if __name__ == "__main__":
    main()
