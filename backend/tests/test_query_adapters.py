import pytest

pytest.importorskip("ezdxf")
pytest.importorskip("shapely")

from app.dxf import Query as DxfQuery  # noqa: E402
from app.query.adapters import to_dxf  # noqa: E402
from app.query.rules import parse_english  # noqa: E402


@pytest.mark.parametrize("q,expected", [
    ("How many windows are drawn on this floor plan?", DxfQuery("count", "window")),
    ("How many apartments are shown on this floor plan?", DxfQuery("count", "unit")),
    ("How many rooms labelled 'Bad' are there on this floor?", DxfQuery("count", "room", label="Bad")),
    ("What is the net floor area of room 7.01 ('Balkon') in m²?", DxfQuery("area", "room", room_id="7.01", label="Balkon")),
    ("What is the net floor area of apartment B in m², excluding balconies?",
     DxfQuery("area", "room", unit_id="B", indoor_only=True)),
    ("What is the total net floor area in m² of all numbered indoor rooms on this floor?",
     DxfQuery("area", "room", indoor_only=True)),
    ("What is the total net area in m² of all rooms labelled 'Zimmer' on this floor?", DxfQuery("area", "room", label="Zimmer")),
])
def test_to_dxf(q, expected):
    assert to_dxf(parse_english(q)) == expected


@pytest.mark.parametrize("q", [
    "How many showers and bathtubs are there in total?",  # combined target: not a DXF kind
    "How many bedrooms are on this floor plan?",  # room category, not a printed label
    "How many doors are shown on the floor plan of 'Level 1'?",  # IFC level scope
    "What is the total length of all walls on 'Plan 1', in metres?",
])
def test_to_dxf_unsupported(q):
    assert to_dxf(parse_english(q)) is None
