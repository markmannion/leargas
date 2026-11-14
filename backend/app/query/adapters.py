"""Translate a parsed `Query` into each engine's own query type.

Returns None when the engine can't express the query; the router should then try another engine
or answer cannot_verify.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .schema import Query

if TYPE_CHECKING:  # app.dxf needs ezdxf/shapely; import lazily so the parser works without them
    from app.dxf import Query as DxfQuery

# Query.target -> app.dxf kind (Swiss Dwellings layer convention)
_DXF_KIND = {
    "door": "door",
    "window": "window",
    "toilet": "toilet",
    "washbasin": "washbasin",
    "bathtub": "bathtub",
    "shower": "shower",
    "stair": "stairs",
    "room": "room",
    "apartment": "unit",
}


def to_dxf(q: Query) -> Optional["DxfQuery"]:
    from app.dxf import Query as DxfQuery

    if q.scope != "plan" or q.op not in ("count", "area") or q.room_type or q.name or q.side_area:
        return None
    kind = _DXF_KIND.get(q.target)
    if kind is None:
        return None

    if q.target == "apartment":
        if q.op == "count":
            return DxfQuery("count", "unit")
        # Net apartment area = sum of its rooms (outdoor excluded if asked).
        if not q.apartment:
            return None
        return DxfQuery("area", "room", unit_id=q.apartment, indoor_only=q.exclude_outdoor)

    if q.op == "area" and kind != "room":
        return None
    return DxfQuery(
        q.op,
        kind,
        room_id=q.room_id,
        label=q.label,
        indoor_only=q.exclude_outdoor or q.numbered_only,
    )
