"""M12 point matching: python tests/test_point_eval.py (no pytest needed)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model.point_eval import match  # noqa: E402


def test_match_one_to_one() -> None:
    gold = [(100, 100), (200, 100)]
    assert match([(101, 99), (199, 101)], gold, 10) == 2          # both hit
    assert match([(101, 99), (102, 100)], gold, 10) == 1          # two preds on one item: only one counts
    assert match([(150, 100)], gold, 10) == 0                     # between items, outside radius
    assert match([], gold, 10) == 0
    assert match([(100, 100)], [], 10) == 0


def test_match_prefers_nearest_pairs() -> None:
    # pred A is near both golds; pred B only near gold 2. Nearest-first must not let A steal gold 2.
    gold = [(0, 0), (10, 0)]
    assert match([(4, 0), (11, 0)], gold, 6) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
