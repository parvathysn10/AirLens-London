
import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


# Resolve paths relative to the project directory, regardless of where
# the pipeline command is launched.
PROJECT_DIR = Path(__file__).resolve().parent

# Run the same analysis workflow for each supported pollutant.
POLLUTANTS = ["NO2", "PM25", "PM10"]


# Execute individual pipeline stages using the current Python environment.
def run_script(script, arguments=None):
    """Run a pipeline script and stop if it fails."""
    command = [sys.executable, str(PROJECT_DIR / script)]

    if arguments:
        command.extend(arguments)

    print(f"\nRunning {script}", flush=True)

    try:
        subprocess.run(
            command,
            cwd=PROJECT_DIR,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        # Stop immediately if a stage fails to avoid analysing
        # incomplete or potentially outdated data.
        print(
            f"\nPipeline failed while running {script} "
            f"(exit code {error.returncode})",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(error.returncode)


# Configure the date range and execute the full data pipeline.
def main():
    parser = argparse.ArgumentParser(
        description="Run the AirLens London data pipeline"
    )

    parser.add_argument(
        "--start",
        default=None,
        help="Start date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--end",
        default=None,
        help="Exclusive end date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download fresh measurement snapshots without overwriting originals",
    )

    parser.add_argument(
        "--latest",
        action="store_true",
        help="Refresh measurements for today and the previous two days",
    )

    args = parser.parse_args()

    # Latest mode uses a rolling three-day window in UTC.
    # Re-fetching recent measurements also allows late updates to be captured.
    if args.latest:
        if args.start or args.end:
            parser.error(
                "--latest cannot be combined with --start or --end"
            )

        # LAQN measurement timestamps use GMT/UTC.
        # Include today and the previous two days.
        today = datetime.now(timezone.utc).date()

        start_date = today - timedelta(days=2)
        end_date = today + timedelta(days=1)

    else:
        # Preserve the existing historical default period.
        try:
            start_date = date.fromisoformat(
                args.start or "2026-10-01"
            )
            end_date = date.fromisoformat(
                args.end or "2026-10-25"
            )
        except ValueError:
            parser.error(
                "Dates must be valid and use YYYY-MM-DD format"
            )

    # An exclusive end date avoids ambiguity between adjacent date windows.
    if end_date <= start_date:
        parser.error("End date must be after start date")

    print("Starting AirLens London pipeline", flush=True)

    print(
        f"Period: {start_date} to {end_date} (end exclusive)",
        flush=True,
    )

    if args.latest:
        print(
            "Latest mode: refreshing recent measurements "
            "for all configured stations",
            flush=True,
        )

    extract_args = [
        "--start", str(start_date),
        "--end", str(end_date),
    ]

    # Latest mode always fetches fresh snapshots.
    if args.refresh or args.latest:
        extract_args.append("--refresh")

    # Stage 1: Download and preserve raw API responses.
    # Extract and store the measurements before analysing them.
    run_script("src/extract.py", extract_args)

    # Stage 2: Validate, transform and load data into DuckDB.
    # The transformation stage handles repeated or updated measurements.
    run_script("src/transform.py")

    # Stage 3: Generate SQL-based summaries for each pollutant.
    # Run the SQL analysis separately for each pollutant.
    for pollutant in POLLUTANTS:
        run_script(
            "src/analyse.py",
            [
                "--start", str(start_date),
                "--end", str(end_date),
                "--pollutant", pollutant,
            ],
        )

    print(
        "\nAirLens London pipeline completed successfully",
        flush=True,
    )


if __name__ == "__main__":
    main()
