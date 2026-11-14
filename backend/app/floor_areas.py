"""Room quantities and sheet evidence, using metre-based CAD footprints.

Printed m² are authoritative for whole-room measurements. Intersections always
measure the actual footprint, including voids; printed m² are never prorated.
"""
from __future__ import annotations

import math

from .region import CannotScope
from .schema import Evidence, PolygonEvidence, RoomArea, Source


def room_footprint(item, by_id):
    from shapely.ops import unary_union

    footprint = item.polygon
    if item.interior_outline_ids:
        footprint = footprint.difference(unary_union([
            by_id[item_id].polygon for item_id in item.interior_outline_ids
        ]))
    if not footprint.is_valid or footprint.area <= 0:
        raise CannotScope("A room has no valid net floor outline.")
    return footprint


def measure_rooms(drawing, query, result, norm=None, region=None, mode="whole_rooms"):
    from shapely.affinity import affine_transform
    from shapely.geometry import box

    by_id = {item.id: item for item in drawing.items}
    selection = box(*region.bbox) if region else None
    matrix = None
    if norm is not None:
        u, v = norm(0, 0)
        ux, vx = norm(1, 0)
        uy, vy = norm(0, 1)
        matrix = [ux - u, uy - u, vx - v, vy - v, u, v]
        if not all(math.isfinite(n) for n in matrix) or abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]) < 1e-20:
            raise CannotScope("The CAD geometry has no usable sheet scale.")
    if region and matrix is None:
        raise CannotScope("The CAD geometry cannot be aligned confidently to the selected sheet.")

    rows, evidence, values, footprints = [], [], [], []
    for item_id in result.item_ids:
        item = by_id[item_id]
        footprint = room_footprint(item, by_id)
        polygon = affine_transform(footprint, matrix) if matrix else None
        measured = polygon
        complete = True
        if selection is not None:
            measured = polygon.intersection(selection)
            if measured.area <= 1e-12:
                continue
            complete = selection.buffer(1e-9).covers(polygon)
            if mode == "whole_rooms" and not complete:
                raise CannotScope(
                    "The region cuts through a room. Select complete rooms to verify their area, "
                    "or switch to Exact selected area to measure the clipped CAD footprint."
                )

        if mode == "intersection":
            value = footprint.area * measured.area / polygon.area
            method = "geometry"
            footprints.append(measured)
        elif query.area_source != "geometry" and item.printed_area_m2 is not None:
            value, method = item.printed_area_m2, "printed"
        else:
            value, method = footprint.area, "geometry"
        if not math.isfinite(value) or value < 0:
            raise CannotScope("A room has no verifiable floor area.")
        label = " ".join(s for s in (item.room_id, item.label) if s) or "Room"
        indices = []
        if measured is not None:
            parts = [measured] if measured.geom_type == "Polygon" else list(measured.geoms)
            for part in parts:
                if part.geom_type != "Polygon" or part.area <= 1e-12:
                    continue
                # Do not clamp an off-sheet outline into a misleading measurement.
                if not box(0, 0, 1, 1).buffer(1e-9).covers(part):
                    continue
                def points(ring):
                    return [(min(1, max(0, x)), min(1, max(0, y))) for x, y in list(ring.coords)[:-1]]
                indices.append(len(evidence))
                evidence.append(Evidence(
                    shape=PolygonEvidence(points=points(part.exterior), holes=[points(ring) for ring in part.interiors]),
                    label=f"{label} {value:g} m²" + (" (selected portion)" if not complete else ""),
                    value=value * part.area / measured.area,
                    source=Source.geometry_dxf,
                ))
        rows.append(RoomArea(id=item.id, label=item.label or "Room", room_id=item.room_id,
                             value=round(value, 6), method=method, complete=complete,
                             evidence_indices=indices))
        values.append(value)

    if not rows and mode == "whole_rooms":
        raise CannotScope("No complete rooms with verifiable areas matched inside the selected region.")
    if mode == "intersection":
        from shapely.ops import unary_union

        summed = math.fsum(footprint.area for footprint in footprints)
        if summed - unary_union(footprints).area > max(1e-12, summed * 1e-8):
            raise CannotScope("Room outlines overlap in the selection; the floor area cannot be summed without double counting.")
        explanation = (
            "Measured the selected region intersected with numbered room floor polygons in CAD metres, "
            "excluding enclosed voids. Printed room areas were not prorated. "
            "Space outside those floor polygons is excluded. Totals are rounded to 0.01 m²."
        )
    else:
        explanation = result.explanation + " Breakdown by numbered room; totals are rounded to 0.01 m²."
        if region:
            explanation += " Only complete rooms inside the selected region are included."
    return round(math.fsum(values), 2), rows, evidence, explanation
