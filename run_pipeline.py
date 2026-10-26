
import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


def run_script(script, arguments=None):
    command = [sys.executable, str(PROJECT_DIR / script)]

    if arguments:
        command.extend(arguments)

    print(f"\nRunning {script}", flush=True)

    subprocess.run(
        command,
        cwd=PROJECT_DIR,
        check=True,
    )


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
        start_date = date.fromisoformat(
            args.start or "2026-10-01"
        )
        end_date = date.fromisoformat(
            args.end or "2026-10-25"
        )

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

    run_script("src/extract.py", extract_args)

    run_script("src/transform.py")

    run_script(
        "src/analyse.py",
        [
            "--start", str(start_date),
            "--end", str(end_date),
            "--pollutant", "NO2",
        ],
    )

    print(
        "\nAirLens London pipeline completed successfully",
        flush=True,
    )


if __name__ == "__main__":
    main()
