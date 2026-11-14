"""Independent checks for generated gold, geometry compatibility and scoring."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from model.synthetic_data import generate, make_scene, questions, split_for, write_dxf
from model.synthetic_eval import evaluate


def test_gold_matches_independent_scene_math_and_geometry(tmp_path):
    from app.dxf import Query, parse_dxf
    for index in range(4):
        scene = make_scene(index, 123)
        path = tmp_path / f"{index}.dxf"
        write_dxf(scene, path)
        drawing = parse_dxf(path)
        assert not drawing.warnings
        for kind, key in (("room", "rooms"), ("window", "windows"), ("door", "doors")):
            assert drawing.query(Query("count", kind)).value == len(scene[key])
        assert drawing.query(Query("area", "room")).value == pytest.approx(scene["width"] * scene["height"], abs=.01)
        for room in scene["rooms"]:
            assert drawing.query(Query("area", "room", room_id=room["id"])).value == pytest.approx(room["w"] * room["h"], abs=.005)
        qs = questions(scene, "clean", "test")
        assert len({(q["path"], q["question"]) for q in qs}) == len(qs)
        assert sum(q["expected"] == "cannot_verify" for q in qs) == 4
        for q in qs:
            if "points" in q:
                assert len(q["points"]) == q["answer"]
                assert all(0 <= v <= 1 for p in q["points"] for v in p)
        for q in qs:
            if q["type"] == "volume" and q["answer"] is not None:
                rid = q["question"].split("room ")[1].split()[0]
                room = next(r for r in scene["rooms"] if r["id"] == rid)
                assert q["answer"] == pytest.approx(room["w"] * room["h"] * scene["ceiling"], abs=.0005)
        assert qs == questions(make_scene(index, 123), "clean", "test")


def test_zero_is_an_answer_and_absent_area_is_not():
    scene = make_scene(0, 123)
    qs = questions(scene, "clean", "test")
    q = next(q for q in qs if q["question"].startswith("How many windows"))
    assert q["answer"] == 0 and q["expected"] == "answer" and q["points"] == []
    assert next(q for q in qs if "room 9.99" in q["question"])["answer"] is None


def test_stratified_group_splits_and_artifacts(tmp_path):
    for difficulty in range(4):
        splits = [split_for(i, 123) for i in range(difficulty, 600, 4)]
        assert splits.count("train") == 120
        assert splits.count("validation") == 15
        assert splits.count("test") == 15
    manifest = generate(tmp_path, 4, 123)
    qs = [json.loads(line) for line in (tmp_path / "questions.jsonl").read_text().splitlines()]
    assert manifest["questions"] == len(qs)
    assert manifest["drawings"] == 8
    for group in {q["group_id"] for q in qs}:
        assert len({q["split"] for q in qs if q["group_id"] == group}) == 1
    for q in qs:
        assert (tmp_path / q["path"]).is_file()
        assert (tmp_path / q["path"]).with_suffix(".dxf").is_file()
    from PIL import Image
    with Image.open(tmp_path / "preview.png") as im:
        assert im.size == (960, 1720)
    with pytest.raises(FileExistsError):
        generate(tmp_path, 4, 123)


def test_scoring_errors_refusals_units_and_missing():
    gold = questions(make_scene(0, 123), "clean", "test")
    zero = next(g for g in gold if g["question"].startswith("How many windows"))
    area = next(g for g in gold if g["type"] == "area" and g["unit"] == "m2" and g["answer"] is not None)
    refusal = next(g for g in gold if g["answer"] is None)
    selected = [zero, area, refusal]
    preds = [dict(id=zero["id"], answer=0, unit="count"),
             dict(id=area["id"], answer=area["answer"] / .3048**2, unit="ft2"),
             dict(id=refusal["id"], answer=None, status="cannot_verify")]
    report, _ = evaluate(selected, preds)
    assert report["overall"]["accuracy"] == 1
    assert report["answerable"]["accuracy"] == 1
    assert report["unanswerable"]["accuracy"] == 1
    assert report["_meta"]["independent_layouts"] == 1
    for bad in (dict(answer=None, error="timeout"), dict(answer=None, ok=False), dict(), dict(answer=7)):
        report, details = evaluate([refusal], [dict(id=refusal["id"], **bad)])
        assert report["overall"]["accuracy"] == 0
        assert details[0]["outcome"] in {"error", "unsupported_answer"}
    report, details = evaluate([refusal], [])
    assert report["overall"]["accuracy"] == 0 and details[0]["outcome"] == "missing"
    report, _ = evaluate([zero], [dict(id=zero["id"], answer=None, status="cannot_verify")])
    assert report["overall"]["accuracy"] == 0
    with pytest.raises(ValueError, match="Mock"):
        evaluate([zero], [dict(id=zero["id"], answer=0, source="mock")])


def test_numeric_tolerance_is_not_exact_match():
    gold = next(g for g in questions(make_scene(0, 123), "clean", "test") if g["type"] == "area" and g["answer"])
    for delta, expected in ((.019, 1), (.021, 0)):
        report, _ = evaluate([gold], [dict(id=gold["id"], answer=gold["answer"] * (1+delta), unit=gold["unit"])])
        assert report["overall"]["accuracy"] == expected
