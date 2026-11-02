
"""Focused regression tests for AirLens extraction, ingestion and daily averages."""

import ast
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest
import requests

from src import transform
from src.extract import fetch_json


# Create synthetic API responses for repeatable tests without network access.
def write_snapshot(folder, pollutant, value):
    """Create a small LAQN snapshot without making an API request."""
    filepath = folder / f"TEST_{pollutant}_2026-10-01_2026-10-02.json"
    filepath.write_text(json.dumps({
        "RawAQData": {
            "@SiteCode": "TEST",
            "@SpeciesCode": pollutant,
            "Data": {
                "@MeasurementDateGMT": "2026-10-01 12:00:00",
                "@Value": str(value),
            },
        }
    }), encoding="utf-8")
    return filepath


# Confirm that processing the same snapshot twice is idempotent.
# The second run should not insert or update any measurements.
def test_reprocessing_unchanged_snapshot_does_not_duplicate_rows(tmp_path):
    snapshot = write_snapshot(tmp_path, "NO2", 12.5)
    con = duckdb.connect(":memory:")
    try:
        transform.create_tables(con)
        with patch.object(transform, "measurement_files", return_value=[snapshot]):
            first = transform.load_measurements(con)
            second = transform.load_measurements(con)
        assert first["inserted"] == 1
        assert second["inserted"] == 0
        assert second["updated"] == 0
        assert con.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM processed_snapshots").fetchone()[0] == 1
    finally:
        con.close()


# Confirm that the composite measurement key includes the pollutant code.
# Different pollutants at the same station and hour must remain separate.
def test_three_pollutants_stay_separate_at_same_station_and_hour(tmp_path):
    snapshots = [write_snapshot(tmp_path, code, value) for code, value in
                 [("NO2", 10), ("PM25", 20), ("PM10", 30)]]
    con = duckdb.connect(":memory:")
    try:
        transform.create_tables(con)
        with patch.object(transform, "measurement_files", return_value=snapshots):
            counts = transform.load_measurements(con)
        rows = con.execute("""
            SELECT pollutant_code, value FROM measurements
            WHERE site_code = 'TEST'
            ORDER BY pollutant_code
        """).fetchall()
        assert counts["inserted"] == 3
        assert rows == [("NO2", 10.0), ("PM10", 30.0), ("PM25", 20.0)]
    finally:
        con.close()


# Simulate a connection failure and check that extraction reports the
# failed endpoint rather than silently continuing with incomplete data.
def test_api_failure_reports_url_and_stops():
    with patch("src.extract.requests.Session") as mock_session:
        session = mock_session.return_value.__enter__.return_value
        session.get.side_effect = requests.ConnectionError("connection lost")
        with pytest.raises(RuntimeError, match="Failed to fetch LAQN data") as exc:
            fetch_json("test-endpoint")
        assert "test-endpoint" in str(exc.value)


# Extract the daily-average calculation function without launching Streamlit.
# Parsing the source allows its calculation logic to be tested independently.
def daily_average_function():
    """Load only the dashboard function, avoiding Streamlit page startup."""
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "calculate_daily_averages")
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["calculate_daily_averages"]


# Test the minimum daily data coverage rule at its boundary.
# Seventeen valid hours are insufficient; eighteen are accepted.
def test_daily_average_requires_at_least_18_valid_hours():
    calculate = daily_average_function()
    times = pd.date_range("2026-10-01", periods=24, freq="h")
    data = pd.concat([
        pd.DataFrame({"site_code": "A", "measured_at": times,
                      "value": [10.0] * 17 + [None] * 7}),
        pd.DataFrame({"site_code": "B", "measured_at": times,
                      "value": [20.0] * 18 + [None] * 6}),
    ], ignore_index=True)
    result = calculate(data, pd.Timestamp("2026-10-01 23:00:00"))
    rows = result.set_index("site_code")
    assert rows.loc["A", "valid_hours"] == 17
    assert pd.isna(rows.loc["A", "daily_average"])
    assert rows.loc["B", "valid_hours"] == 18
    assert rows.loc["B", "daily_average"] == pytest.approx(20.0)


# Exclude the current incomplete day from daily-average comparisons.
# Only the fully completed 1 October period should be returned.
def test_daily_averages_exclude_unfinished_day():
    calculate = daily_average_function()
    times = pd.date_range("2026-10-01", periods=24, freq="h")
    next_day = pd.date_range("2026-10-02", periods=20, freq="h")
    data = pd.DataFrame({"site_code": "A",
                         "measured_at": times.append(next_day),
                         "value": [10.0] * 24 + [20.0] * 20})
    result = calculate(data, pd.Timestamp("2026-10-02 19:00:00"))
    assert len(result) == 1
    assert result.iloc[0]["date"] == pd.Timestamp("2026-10-01")
    assert result.iloc[0]["daily_average"] == pytest.approx(10.0)
