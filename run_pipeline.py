
import argparse
import subprocess
import sys
from datetime import date
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
        default="2026-10-01",
        help="Start date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--end",
        default="2026-10-25",
        help="Exclusive end date in YYYY-MM-DD format",
    )

    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    if end_date <= start_date:
        parser.error("End date must be after start date")

    print("Starting AirLens London pipeline", flush=True)
    print(
        f"Period: {start_date} to {end_date} (end exclusive)",
        flush=True,
    )

    run_script(
        "src/extract.py",
        [
            "--start", str(start_date),
            "--end", str(end_date),
        ],
    )

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
