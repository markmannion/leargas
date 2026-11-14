"""Sheet reader units that need no drawing files: row/label joining, scale parsing, tool picking."""

import pytest

pytest.importorskip("numpy")

from app.sheet import answer as A
from app.sheet.scale import _dimension_chain, _scale_bar
from app.sheet.words import Sheet, Text, blocks, rows


def T(text, x0, y0, x1, y1, conf=0.99):
    return Text(text, (x0, y0, x1, y1), conf)


def test_rows_join_label_and_value_but_not_columns():
    texts = [T("TOTAL SECOND FLOOR =", 100, 100, 500, 130), T("26,562 SF", 700, 100, 880, 130),
             T("SOME NOTE TEXT", 1300, 100, 1600, 130), T("WEST WING", 1700, 100, 1900, 130)]
    got = [r.text for r in rows(texts)]
    assert "TOTAL SECOND FLOOR = 26,562 SF" in got
    assert "SOME NOTE TEXT" in got  # the wide gap to the next column breaks the row


def test_blocks_stack_centred_lines():
    texts = [T("Secondary", 100, 100, 220, 120), T("Classroom", 102, 124, 218, 144), T("Corridor", 600, 100, 700, 120)]
    assert sorted(b.text for b in blocks(texts)) == ["Corridor", "Secondary Classroom"]


def test_scale_bar_metric_and_imperial():
    ppm, _ = _scale_bar([T("0", 100, 1000, 110, 1020), T("10m", 1250, 1000, 1290, 1020), T("20m", 2430, 1000, 2470, 1020)])
    assert ppm == pytest.approx((2450 - 105) / 20, rel=1e-6)
    ppm, _ = _scale_bar([T("0'", 0, 0, 10, 20), T("40'", 1205, 0, 1225, 20)])
    assert ppm == pytest.approx((1215 - 5) / (40 * 0.3048), rel=1e-6)


def test_dimension_chain_gives_px_per_m():
    # labels sit (a + b) / 2 apart at 0.25 px/mm
    vals = [600, 3450, 600, 3600, 600, 3600, 600]
    xs, x = [], 0.0
    for i, v in enumerate(vals):
        if i:
            x += 0.25 * (vals[i - 1] + v) / 2
        xs.append(x)
    texts = [T(str(v), cx - 30, 50, cx + 30, 70) for v, cx in zip(vals, xs)]
    ppm, _ = _dimension_chain(texts)
    assert ppm == pytest.approx(250, rel=0.01)


def _sheet(texts):
    return Sheet("x.png", "x.png", 4000, 3000, "ocr", texts)


def test_tags_count_distinct_numbers():
    s = _sheet([T("PS-1", 0, 0, 40, 10), T("PS-1", 100, 0, 140, 10), T("PS-3", 200, 0, 240, 10), T("FP-1", 0, 50, 40, 60)])
    r = A.tool_tags(s, "How many pipe supports are there?")
    assert r.value == 2 and r.unit == "count" and len(r.evidence) == 3


def test_printed_value_prefers_exact_row():
    s = _sheet([T("WEST WING DORMITORY =", 0, 0, 400, 30), T("6,095 SF", 580, 0, 730, 30),
                T("WEST WING CIRCULATION =", 0, 60, 420, 90), T("914 SF", 600, 60, 700, 90)])
    r = A.tool_printed(s, "What is the area of the west wing circulation?", A._q_kind("area of west wing circulation"))
    assert r.value == 914 and r.unit == "ft2"


def test_label_count():
    s = _sheet([T("Group Room", 0, 0, 100, 20), T("Group Room", 300, 0, 400, 20), T("Plant Room", 600, 0, 700, 20)])
    assert A.tool_label_count(s, "How many group rooms are there?").value == 2


def test_label_count_all_rooms():
    s = _sheet([T("Upload feature - sample floor plan", 0, 0, 400, 20), T("Living room", 0, 100, 100, 120),
                T("Bedroom", 300, 100, 400, 120), T("Kitchen", 300, 300, 400, 320), T("Balcony", 0, 300, 100, 320)])
    assert A.tool_label_count(s, "How many rooms are there?").value == 3
    assert A.tool_label_count(s, "How many bedrooms are there?").value == 1
