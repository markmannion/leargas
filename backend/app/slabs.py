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
        slab_types=_types(items),
    ) for (thickness, _), items in sorted(buckets.items(), key=lambda pair: (
        pair[0][0] is None, pair[0][0] or 0, pair[0][1],
    ))]


def _types(items: list[SlabArea]) -> list[str]:
    area = defaultdict(float)
    for i in items:
        if i.slab_type:
            area[i.slab_type] += i.value
    return [t for t, _ in sorted(area.items(), key=lambda pair: -pair[1])]


def slab_explanation(rows: list[SlabArea]) -> str:
    unknown = [r for r in rows if r.specification_status == "unknown"]
    no_bars = [r for r in unknown if not r.reinforcement]
    note = ""
    if unknown:
        note = (f" {len(unknown)} slab/zone(s), {fsum(r.value for r in unknown):.2f} m², have an incomplete specification"
                + (f" ({len(no_bars)} with no bar/reinforcement data in the source)" if no_bars else "")
                + "; their measured area is kept.")
    return f"Slab area by type, grouped by thickness and bars, over {len(rows)} slab/zone(s).{note}"
