import pytest

from score import drawing_key, score, score_one


def g(answer, type_="count", unit="count", path="data/swiss_dwellings/a.pdf", q="q"):
    return {"path": path, "question": q, "answer": answer, "unit": unit, "type": type_}


def p(answer, unit=None, status=None, path="data/swiss_dwellings/a.pdf", q="q"):
    d = {"path": path, "question": q, "answer": answer}
    if unit:
        d["unit"] = unit
    if status:
        d["status"] = status
    return d


@pytest.mark.parametrize("pred,ok", [(5, True), (5.0, True), ("5", True), (4, False), (5.4, False), ("five", False)])
def test_count_exact(pred, ok):
    assert score_one(g(5), p(pred))["correct"] is ok


@pytest.mark.parametrize("pred,tol,ok", [(102.0, 0.02, True), (102.1, 0.02, False), (98.0, 0.02, True),
                                         (101.0, 0.01, True), (101.5, 0.01, False)])
def test_area_tolerance(pred, tol, ok):
    assert score_one(g(100.0, "area", "m2"), p(pred, "m2"), tol)["correct"] is ok


def test_unit_conversion_and_mismatch():
    assert score_one(g(10.0, "area", "m2"), p(107.639, "ft2"))["correct"]
    assert score_one(g(10.0, "area", "m2"), p(10.0, "m"))["outcome"] == "unit_mismatch"
    assert score_one(g(10.0, "area", "m2"), p(10.0))["correct"]  # no unit -> assume gold unit


def test_abstain_and_missing():
    assert score_one(g(3), p(None, status="cannot_verify"))["outcome"] == "abstain"
    assert score_one(g(3), p(3, status="cannot_verify"))["outcome"] == "abstain"
    assert score_one(g(3), None)["outcome"] == "missing"


def test_comma_decimal():
    assert score_one(g(27.66, "area", "m2"), p("27,7 m²"))["correct"]


def test_aggregate_and_split():
    gold = [
        g(5, q="a"), g(3, q="b"),
        g(50.0, "area", "m2", q="c"),
        g(7, path="data/cubicasa5k/x.png", q="d"),
        g("Revit", "text", None, q="e"),
    ]
    preds = [p(5, q="a"), p(None, status="cannot_verify", q="b"), p(50.5, "m2", q="c"), p("revit", q="e")]
    r = score(gold, preds)
    assert r["overall"]["n"] == 4  # text excluded from headline
    assert r["overall"]["accuracy"] == 0.5
    assert r["overall"]["coverage"] == 0.5
    assert r["overall"]["precision"] == 1.0
    assert r["overall"]["outcomes"] == {"correct": 2, "abstain": 1, "missing": 1}
    assert r["text_exact_match(unscored)"]["accuracy"] == 1.0
    assert r["type/area"]["accuracy_strict_1pct"] == 1.0

    # held out by stem: listing the .dxf twin holds out the .pdf questions
    r2 = score(gold, preds, split=["data/swiss_dwellings/a.dxf"])
    assert r2["overall"]["n"] == 3
    assert "source/cubicasa5k" not in r2


def test_drawing_key():
    assert drawing_key("data/swiss_dwellings/site1.pdf") == drawing_key("data/swiss_dwellings/site1.dxf\n")
