def classify_coverage(valid_hours, expected_hours):
    if expected_hours <= 0:
        return "No expected data"

    percentage = (valid_hours / expected_hours) * 100

    if valid_hours == 0:
        return "No valid data"
    elif percentage >= 90:
        return "Good coverage"
    elif percentage >= 75:
        return "Moderate coverage"
    else:
        return "Low coverage"


def classify_freshness(latest_reading, period_end):
    if latest_reading is None:
        return "No valid readings"

    from datetime import datetime, timedelta

    latest = datetime.fromisoformat(str(latest_reading))
    end = datetime.fromisoformat(str(period_end))

    if latest >= end - timedelta(days=2):
        return "Recent"
    else:
        return "Outdated"