"""Structured query: what the geometry engines (DXF, IFC) execute.

A question in any language becomes one `Query`. The engines never see the question text.

Examples
--------
"How many windows are drawn on this floor plan?"
    {op: count, target: window, scope: plan}
"Wie viele Räume mit der Bezeichnung «Küche» gibt es in diesem Geschoss?"
    {op: count, target: room, scope: plan, label: "Küche"}
"What is the net floor area of room 7.01 ('Balkon') in m²?"
    {op: area, target: room, scope: plan, room_id: "7.01", label: "Balkon", unit: m2}
"What is the total length of all walls on 'Grundplan', in metres?"
    {op: length, target: wall, scope: level, level: "Grundplan", unit: m}
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Op(str, Enum):
    count = "count"
    area = "area"
    length = "length"
    volume = "volume"


class Target(str, Enum):
    # elements / fixtures
    door = "door"
    window = "window"
    toilet = "toilet"  # WC seat / toilet bowl
    washbasin = "washbasin"
    sink_or_washbasin = "sink_or_washbasin"  # kitchen sinks + basins combined
    bathtub = "bathtub"
    shower = "shower"
    shower_or_bathtub = "shower_or_bathtub"
    sanitary_fixture = "sanitary_fixture"
    light_fixture = "light_fixture"
    wall = "wall"
    slab = "slab"
    column = "column"
    beam = "beam"
    stair = "stair"
    # spatial
    room = "room"  # a room / IfcSpace; narrowed by room_type, label, room_id or name
    apartment = "apartment"
    storey = "storey"


class RoomType(str, Enum):
    """Canonical room categories (used where a question names a category, not a printed label)."""

    bedroom = "bedroom"
    bathroom = "bathroom"  # bathrooms / washrooms, excluding separate WC rooms
    wc = "wc"  # separate toilet rooms
    kitchen = "kitchen"  # incl. kitchenettes, open and utility kitchens
    sauna = "sauna"
    balcony = "balcony"


class Scope(str, Enum):
    plan = "plan"  # the drawing the question is attached to
    level = "level"  # a named storey of a model (`level`)
    model = "model"  # the whole IFC model (`model`)


class Query(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    op: Op
    target: Target
    scope: Scope = Scope.plan
    room_type: Optional[RoomType] = None
    label: Optional[str] = Field(None, description="Printed room label to match exactly, e.g. 'Schlafzimmer'")
    room_id: Optional[str] = Field(None, description="Room number, e.g. '7.01'")
    name: Optional[str] = Field(None, description="IFC space name, e.g. 'Kitchen (A103)'")
    apartment: Optional[str] = Field(None, description="Apartment letter, e.g. 'B'")
    level: Optional[str] = Field(None, description="Storey name, e.g. 'Level 1'")
    model: Optional[str] = Field(None, description="IFC model name")
    exclude_outdoor: bool = Field(False, description="Exclude balconies, loggias, terraces, other outdoor spaces")
    numbered_only: bool = Field(False, description="Only numbered indoor rooms (also excludes shafts and voids)")
    side_area: bool = Field(False, description="Wall side area rather than footprint")
    unit: Optional[str] = Field(None, description="count | m | m2 | m3 | ft2 ...")
    group_by: Optional[Literal["thickness_reinforcement"]] = None
    type_mark: Optional[str] = Field(None, description="Door/window type mark, e.g. 'D01'")
    count_basis: Literal["assemblies", "leaves", "symbols"] = Field(
        "assemblies",
        description="Doors/windows: physical assemblies (a double door is one), door leaves, "
                    "or symbols as drawn (duplicates included)",
    )

    @model_validator(mode="after")
    def _slab_grouping(self) -> "Query":
        if self.group_by and (self.op != "area" or self.target != "slab" or self.side_area):
            raise ValueError("Thickness/reinforcement grouping requires slab area")
        if (self.type_mark or self.count_basis != "assemblies") and (
            self.op != "count" or self.target not in ("door", "window")
        ):
            raise ValueError("Type marks and count bases apply to door/window counts")
        if self.count_basis == "leaves" and self.target != "door":
            raise ValueError("Leaf counts apply to doors")
        return self


class ParseResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    query: Optional[Query] = Field(None, description="null when the question can't be mapped to a query")
    parser: str = Field(description="template | rules | llm | none")
    confidence: float = Field(ge=0.0, le=1.0)
    template: Optional[str] = Field(None, description="Normalized template that matched, for debugging")
    args: List[str] = Field(default_factory=list)
    reason: Optional[str] = None
