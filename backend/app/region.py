"""Spatial scope for geometry queries and crops of the exact sheet shown by the UI."""
from __future__ import annotations

import math
import re
from dataclasses import replace

from . import drawings
from .schema import Region


class CannotScope(ValueError):
    pass


def geometry_question(question: str) -> str:
    """The explicit selection supplies deictic scope; keep other question qualifiers intact."""
    question = re.sub(
        r"\b(?:in|inside|within)\s+(?:(?:this|the|my)\s+)?"
        r"(?:(?:selected|drawn|highlighted)\s+)?(?:region|area|box|selection)\b",
        "", question, flags=re.I,
    )
    question = re.sub(r"\b(?:(?:in|inside|within)\s+)?here\b", "", question, flags=re.I)
    return re.sub(r"\s+", " ", question).strip()


def scope_dxf(result, query, drawing, norm, region: Region):
    """Count item centers; sum complete rooms only, never prorate printed room areas."""
    from shapely.geometry import Polygon, box

    selection = box(*region.bbox)
    by_id = {item.id: item for item in drawing.items}
    selected = []
    for item_id in result.item_ids:
        item = by_id.get(item_id)
        if item is None or len(item.points) < 3:
            raise CannotScope("An item's position cannot be mapped to the selected region.")
        polygon = Polygon([norm(x, y) for x, y in item.points])
        if not polygon.is_valid or polygon.area <= 0:
            raise CannotScope("An item's outline cannot be mapped to the selected region.")
        if query.operation == "count":
            if selection.covers(polygon.centroid):
                selected.append(item)
        elif selection.intersection(polygon).area > 1e-12:
            if not selection.buffer(1e-9).covers(polygon):
                raise CannotScope(
                    "The region cuts through a room. Select complete rooms to verify their area; "
                    "printed room areas cannot measure a partial room."
                )
            selected.append(item)
    if query.operation == "count":
        value = len(selected)
        explanation = f"Counted {value} {query.kind} objects whose centers are inside the selected region."
    else:
        values = [(item.geometric_area_m2 if query.area_source == "geometry" else
                   item.printed_area_m2 if item.printed_area_m2 is not None or query.area_source == "printed"
                   else item.geometric_area_m2) for item in selected]
        if not values or any(value is None for value in values):
            raise CannotScope("No complete rooms with verifiable areas matched inside the selected region.")
        value = round(math.fsum(values), 2)
        explanation = f"{result.explanation} Only complete rooms inside the selected region are included."
    return replace(result, value=value, item_ids=[item.id for item in selected], explanation=explanation)


def crop_sheet(rel: str, region: Region):
    """Return a PIL crop and its actual normalized bounds for reprojecting model points.

    Use the served PDF page, rather than assuming its PNG twin has identical framing.
    Pixel bounds are rounded inward so no material outside the selection reaches the model.
    """
    from PIL import Image

    kind = drawings.render_kind(rel)
    if kind == "pdf":
        path = drawings._render_pdf(drawings._resolve(rel), region.page)
    elif kind == "image":
        path = drawings._resolve(rel)
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise CannotScope("This sheet format cannot be cropped for the image model.")
    else:
        raise CannotScope("No raster sheet is available for a region crop; try the geometry engine.")
    with Image.open(path) as image:
        width, height = image.size
        x0, y0, x1, y1 = region.bbox
        bounds = (math.ceil(x0 * width), math.ceil(y0 * height),
                  math.floor(x1 * width), math.floor(y1 * height))
        if bounds[2] - bounds[0] < 2 or bounds[3] - bounds[1] < 2:
            raise CannotScope("The selected region is too small. Draw a larger region.")
        cropped = image.crop(bounds)
    return cropped, (bounds[0] / width, bounds[1] / height, bounds[2] / width, bounds[3] / height)
