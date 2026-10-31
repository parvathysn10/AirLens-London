
from unittest.mock import patch

import pytest

from src.extract import (
    fetch_json,
    validate_measurement_response,
)
from src.quality import classify_coverage, classify_freshness
from src.transform import parse_number


def test_quality_classification():
    assert classify_coverage(95, 100) == "Good coverage"
    assert classify_coverage(80, 100) == "Moderate coverage"
    assert classify_coverage(40, 100) == "Low coverage"
    assert classify_coverage(0, 100) == "No valid data"

    assert classify_freshness(
        "2026-10-24 12:00:00",
        "2026-10-25 00:00:00",
    ) == "Recent"

    assert classify_freshness(
        "2026-10-13 13:00:00",
        "2026-10-25 00:00:00",
    ) == "Outdated"

    assert classify_freshness(
        None,
        "2026-10-25 00:00:00",
    ) == "No valid readings"


def test_parse_number_validation():
    assert parse_number("18.5") == 18.5
    assert parse_number("") is None
    assert parse_number(None) is None

    with pytest.raises(ValueError):
        parse_number("nan")

    with pytest.raises(ValueError):
        parse_number("inf")

    with pytest.raises(ValueError):
        parse_number("-inf")

    with pytest.raises(ValueError):
        parse_number("not_a_number")


def test_measurement_response_validation():
    valid_empty = {
        "RawAQData": {
            "@SiteCode": "BG1",
            "@SpeciesCode": "NO2",
            "Data": None,
        }
    }

    assert validate_measurement_response(
        valid_empty, "BG1", "NO2"
    ) == []

    malformed = {"unexpected": "response"}

    with pytest.raises(ValueError):
        validate_measurement_response(
            malformed, "BG1", "NO2"
        )

    with pytest.raises(ValueError):
        validate_measurement_response(
            valid_empty, "BT8", "NO2"
        )


def test_fetch_json_retry_configuration():
    with patch("src.extract.requests.Session") as mock_session:
        session = mock_session.return_value.__enter__.return_value

        response = session.get.return_value
        response.json.return_value = {"status": "ok"}

        result = fetch_json("test")

        assert result == {"status": "ok"}

        adapter = session.mount.call_args.args[1]
        retries = adapter.max_retries

        assert retries.total == 3
        assert retries.backoff_factor == 1
        assert set(retries.status_forcelist) == {
            429, 500, 502, 503, 504
        }
        assert "GET" in retries.allowed_methods


if __name__ == "__main__":
    test_quality_classification()
    test_parse_number_validation()
    test_measurement_response_validation()
    test_fetch_json_retry_configuration()
    print("All quality and extraction validation tests passed")
