from src.quality import classify_coverage, classify_freshness


def main():
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

    print("All quality classification tests passed")


if __name__ == "__main__":
    main()