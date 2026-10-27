
from pathlib import Path

from src.transform import snapshot_priority


def test_snapshot_priority():
    older = Path(
        "BL0_NO2_2026-10-24_2026-10-27_20261026T100000000000Z.json"
    )

    newer = Path(
        "BL0_NO2_2026-10-24_2026-10-27_20261026T120000000000Z.json"
    )

    original = Path(
        "BL0_NO2_2026-10-24_2026-10-27.json"
    )

    assert snapshot_priority(original) < snapshot_priority(older)
    assert snapshot_priority(older) < snapshot_priority(newer)

    print("Snapshot priority ordering test passed")


if __name__ == "__main__":
    test_snapshot_priority()
