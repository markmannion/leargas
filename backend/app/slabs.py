"""Shared slab takeoff and grouping. Unknown specifications never erase measured area."""
from collections import defaultdict
from math import fsum
import re
import unicodedata

from .schema import SlabArea, SlabGroup


def specification_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(unicodedata.normalize("NFKC", value).split()).strip()
    if value.casefold() in ("", "-", "—", "?", "n/a", "none", "unknown", "not specified", "unspecified", "notdefined", "undefined", "not available", "tbd"):
        return None
    return value


def specification_key(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def group_slabs(rows: list[SlabArea]) -> list[SlabGroup]:
    buckets = defaultdict(list)
    for row in rows:
        row.specification_status = "known" if row.thickness_mm is not None and row.reinforcement else "unknown"
        key = (round(row.thickness_mm, 6) if row.thickness_mm else None, specification_key(row.reinforcement))
        buckets[key].append(row)
    return [SlabGroup(
        thickness_mm=thickness, reinforcement=items[0].reinforcement,
        specification_status=items[0].specification_status,
        value=fsum(i.value for i in items), slab_ids=[i.id for i in items],
    ) for (thickness, _), items in sorted(buckets.items(), key=lambda pair: (
        pair[0][0] is None, pair[0][0] or 0, pair[0][1],
    ))]


def slab_explanation(rows: list[SlabArea]) -> str:
    unknown = [r for r in rows if r.specification_status == "unknown"]
    note = (f" {len(unknown)} slab/zone(s), {fsum(r.value for r in unknown):g} m², have an unknown specification; "
            "their measurable area is retained." if unknown else "")
    return f"Slab area grouped by thickness and reinforcement over {len(rows)} slab/zone(s).{note}"
