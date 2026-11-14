"""C1 integrity: no held-out drawing leaks into training data or between twins.
python tests/test_splits.py  (or pytest)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model.common import REPO_ROOT, SPLITS_DIR, group_key, is_heldout, load_jsonl, load_questions  # noqa: E402


def test_twins_share_group():
    assert group_key("data/swiss_dwellings/a_b.pdf") == group_key("data/swiss_dwellings/a_b.png") == group_key("data/swiss_dwellings/a_b.dxf")
    assert group_key("data/ifc_models/bimspeed-vitoria_ald26-before_plan-02-p1.pdf") == group_key(
        "data/ifc_models/bimspeed-vitoria_ald26-before.ifc")
    assert group_key("data/opening_design/CTR/Most Current Set/x.pdf") == "opening_design/CTR"


def test_sets_are_heldout_or_unlabelled():
    labelled = {q["path"] for q in load_questions()}
    for name in ("demo_questions.jsonl", "judge_questions.jsonl", "raster_eval.jsonl"):
        p = SPLITS_DIR / name
        if not p.exists():
            continue
        for r in load_jsonl(p):
            assert is_heldout(r["path"]) or r["path"] not in labelled, (name, r["path"])


def test_sft_has_no_heldout():
    for p in (REPO_ROOT / "data" / "sft").glob("*.jsonl"):
        bad = [r["image"] for r in load_jsonl(p) if is_heldout(r["image"])]
        assert not bad, (p.name, bad[:3])


def test_split_not_trivial():
    qs = load_questions()
    ho = sum(is_heldout(q["path"]) for q in qs)
    assert 0.03 < ho / len(qs) < 0.10, ho / len(qs)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
