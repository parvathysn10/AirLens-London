
from pathlib import Path

from src.transform import snapshot_priority


# Verify that measurement snapshots are ordered by download time.
# This prevents older downloaded data from taking priority over newer data.
def test_snapshot_priority():
    # An earlier refreshed snapshot downloaded at 10:00 UTC.
    older = Path(
        "BL0_NO2_2026-10-24_2026-10-27_20261026T100000000000Z.json"
    )

    # A later refreshed snapshot downloaded at 12:00 UTC.
    newer = Path(
        "BL0_NO2_2026-10-24_2026-10-27_20261026T120000000000Z.json"
    )

    # The original snapshot has no download timestamp in its filename.
    # It should rank before both refreshed snapshots.
    original = Path(
        "BL0_NO2_2026-10-24_2026-10-27.json"
    )

    # Check the expected chronological priority:
    # original snapshot < earlier refresh < later refresh.
    assert snapshot_priority(original) < snapshot_priority(older)
    assert snapshot_priority(older) < snapshot_priority(newer)

    print("Snapshot priority ordering test passed")


if __name__ == "__main__":
    test_snapshot_priority()
