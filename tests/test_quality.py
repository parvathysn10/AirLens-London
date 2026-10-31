
import pytest

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


if __name__ == "__main__":
    test_quality_classification()
    test_parse_number_validation()
    print("All quality classification and number validation tests passed")
