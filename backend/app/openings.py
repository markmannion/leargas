"""Door/window inventory: the numbered, reviewable list behind a door or window count.

Counting rule (both engines):
  - one row per physical assembly. A double door is one row with `leaves=2`; the count of
    leaves is a separate question ("count door leaves").
  - a symbol drawn twice on top of itself (common in the Swiss exports) is one row; the copy is
    listed under `duplicates`. Questions that ask what is *drawn* still count every symbol, which
    is the dataset's convention, and the explanation says how many were duplicates.
  - IFC: occurrences only (IfcDoor/IfcWindow); types, styles and schedule tags are never counted.

Numbers follow reading order on the sheet (top to bottom, then left to right), so marker #3 on the
plan is row 3 of the table.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from .schema import Evidence, OpeningItem, PointEvidence, PolygonEvidence, Source

ROW = 1.5  # m: anchors within this height read as one row


def _clip(p: Tuple[float, float]) -> Tuple[float, float]:
    return (min(max(p[0], 0.0), 1.0), min(max(p[1], 0.0), 1.0))


def _row_label(o: OpeningItem) -> str:
    bits = [f"#{o.number}"]
    if o.type_mark:
        bits.append(o.type_mark)
    if o.leaves and o.leaves > 1:
        bits.append("double" if o.leaves == 2 else f"{o.leaves} leaves")
    if o.location:
        bits.append(" / ".join(o.location))
    return " · ".join(bits)


def dxf_inventory(drawing, item_ids: Sequence[str],
                  norm: Optional[Callable[[float, float], Tuple[float, float]]]) -> Tuple[List[OpeningItem], List[Evidence], str]:
    """Rows + numbered point markers for the DXF items a count selected, and a note on duplicates."""
    by_id = {i.id: i for i in drawing.items}
    picked = [by_id[i] for i in item_ids if i in by_id and by_id[i].kind in ("door", "window")]
    heads, dupes = {}, {}
    for it in picked:
        head = by_id.get(it.assembly_id or it.id, it)
        heads.setdefault(head.id, head)
    for it in drawing.items:
        if it.kind in ("door", "window") and it.duplicate_of and (it.assembly_id in heads):
            dupes.setdefault(it.assembly_id, []).append(it.id)
    # Doors joined into a double door: the second leaf's symbol is listed as part of the first.
    ordered = sorted(heads.values(), key=lambda h: (-round(h.anchor[1] / ROW), h.anchor[0]))
    rows, evidence = [], []
    for n, h in enumerate(ordered, 1):
        row = OpeningItem(number=n, id=h.id, kind=h.kind, location=list(h.location),
                          leaves=h.leaves or None, width_m=h.width_m, duplicates=dupes.get(h.id, []))
        if norm is not None:
            # The viewer tags evidence i with "i+1", so the symbol outline carries row n's number.
            pts = [_clip(norm(x, y)) for x, y in h.points]
            shape = PolygonEvidence(points=pts) if len(pts) >= 3 else PointEvidence(point=_clip(norm(*h.anchor)))
            row.evidence_index = len(evidence)
            evidence.append(Evidence(shape=shape, label=_row_label(row), source=Source.geometry_dxf))
        rows.append(row)
    n_dupes = sum(len(v) for v in dupes.values())
    note = ""
    if len(picked) > len(rows) and n_dupes:
        note = (f" {n_dupes} of these symbols are exact duplicates drawn on top of another, "
                f"so the plan shows {len(rows)} physical {picked[0].kind}s.")
    return rows, evidence, note


def ifc_inventory(items, kind: str) -> List[OpeningItem]:
    ordered = sorted(items, key=lambda i: (i.storey or "", i.type_mark or "", i.mark or "", i.guid))
    return [OpeningItem(number=n, id=i.guid, kind=kind, mark=i.mark, type_mark=i.type_mark,
                        type_name=i.type_name, level=i.storey, location=list(i.location),
                        leaves=i.leaves or None, width_m=i.width_m or None)
            for n, i in enumerate(ordered, 1)]
