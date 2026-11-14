"""Answer schema — the contract between the geometry engine, the Gemma models and the frontend.

Every answer, whatever produced it, is an `Answer`. Field names `path`, `question`, `answer`,
`unit`, `type` match the dataset's questions.jsonl exactly so predictions can be scored directly.

Evidence coordinates are normalized to [0, 1] against the rendered image of the drawing
(the PNG, or the given page of the PDF): origin top-left, x to the right, y downwards.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit01 = Annotated[float, Field(ge=0.0, le=1.0)]
Point = Tuple[Unit01, Unit01]


class QuestionType(str, Enum):
    count = "count"
    area = "area"
    length = "length"
    volume = "volume"
    text = "text"
    other = "other"


class Unit(str, Enum):
    count = "count"
    m = "m"
    m2 = "m2"
    m3 = "m3"
    ft = "ft"
    ft2 = "ft2"
    ft3 = "ft3"


class Status(str, Enum):
    verified = "verified"  # one confident source, or two that agree
    partial = "partial"  # an answer, but weak or only partly supported evidence
    disagreement = "disagreement"  # geometry and model both answered and differ
    cannot_verify = "cannot_verify"  # no confident source; `answer` is null


class Source(str, Enum):
    geometry_dxf = "geometry_dxf"
    geometry_ifc = "geometry_ifc"
    gemma_ft = "gemma_ft"
    gemma_base = "gemma_base"
    sheet_reader = "sheet_reader"  # text + lines read off a large sheet (app.sheet), no CAD twin needed
    mock = "mock"


class PolygonEvidence(BaseModel):
    kind: Literal["polygon"] = "polygon"
    points: List[Point] = Field(min_length=3)
    holes: List[List[Point]] = Field(default_factory=list, description="Interior rings excluded from the measured area")


class BBoxEvidence(BaseModel):
    kind: Literal["bbox"] = "bbox"
    bbox: Tuple[Unit01, Unit01, Unit01, Unit01] = Field(description="[x0, y0, x1, y1]")

    @model_validator(mode="after")
    def _ordered(self) -> "BBoxEvidence":
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError("bbox must be [x0, y0, x1, y1] with x0<=x1 and y0<=y1")
        return self


class PointEvidence(BaseModel):
    kind: Literal["point"] = "point"
    point: Point


Shape = Annotated[Union[PolygonEvidence, BBoxEvidence, PointEvidence], Field(discriminator="kind")]


class Evidence(BaseModel):
    """One highlighted item on the drawing — e.g. one counted window, or one room polygon."""

    shape: Shape
    page: int = Field(0, ge=0, description="0-based page index for multi-page PDFs; 0 for images")
    label: Optional[str] = Field(None, description='e.g. "window", "Living Room 27.7 m²"')
    value: Optional[float] = Field(None, description="This item's contribution, e.g. a room's m²")
    source: Optional[Source] = None


class Region(BaseModel):
    """A non-empty selection in the same normalized coordinates as sheet evidence."""

    bbox: Tuple[Unit01, Unit01, Unit01, Unit01]
    page: Literal[0] = 0

    @model_validator(mode="after")
    def _nonempty(self) -> "Region":
        x0, y0, x1, y1 = self.bbox
        if x1 <= x0 or y1 <= y0:
            raise ValueError("region must have positive width and height")
        return self


class AskRequest(BaseModel):
    path: str = Field(description='Dataset path, e.g. "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"')
    question: str
    type: Optional[QuestionType] = Field(None, description="Hint if known; otherwise inferred")
    engine: Optional[Literal["auto", "geometry", "gemma_ft", "gemma_base", "sheet"]] = "auto"
    region: Optional[Region] = None
    area_mode: Literal["whole_rooms", "intersection"] = "whole_rooms"
    room_breakdown: bool = Field(False, description="Require a geometry-backed floor-area breakdown; bypass scalar demo answers")
    slab_breakdown: bool = Field(False, description="Require slab areas grouped by thickness and reinforcement")

    @model_validator(mode="after")
    def _area_selection(self) -> "AskRequest":
        if self.area_mode == "intersection" and self.region is None:
            raise ValueError("intersection area measurement requires a region")
        return self


class RoomArea(BaseModel):
    id: str
    label: str
    room_id: Optional[str] = None
    level: Optional[str] = None
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: Literal["m2"] = "m2"
    method: Literal["printed", "geometry", "quantity"]
    complete: bool = True
    evidence_indices: List[int] = Field(default_factory=list)


class SourceAnswer(BaseModel):
    """What an individual source said, kept so the UI can show agreement/disagreement."""

    source: Source
    answer: Union[int, float, str, None]
    unit: Optional[Unit] = None
    confidence: float = Field(ge=0.0, le=1.0)


class SpecificationReference(BaseModel):
    path: str
    page: int = Field(0, ge=0)
    label: str


class SlabArea(BaseModel):
    id: str
    mark: Optional[str] = None
    slab_type: Optional[str] = None
    level: Optional[str] = None
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: Literal["m2"] = "m2"
    method: Literal["geometry", "quantity"]
    thickness_mm: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    reinforcement: Optional[str] = None
    specification_status: Literal["known", "unknown"] = "unknown"
    references: List[SpecificationReference] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    evidence_indices: List[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _specification_status(self) -> "SlabArea":
        self.specification_status = "known" if self.thickness_mm is not None and self.reinforcement else "unknown"
        return self


class SlabGroup(BaseModel):
    thickness_mm: Optional[float] = None
    reinforcement: Optional[str] = None
    specification_status: Literal["known", "unknown"]
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: Literal["m2"] = "m2"
    slab_ids: List[str]
    slab_types: List[str] = Field(default_factory=list, description="Slab type names in this group, largest area first")


class OpeningItem(BaseModel):
    """One counted door or window: a row of the reviewable inventory and a numbered marker."""

    number: int = Field(ge=1, description="1-based; matches the marker on the sheet")
    id: str = Field(description="DXF handle of the (first) leaf, or IFC GlobalId")
    kind: Literal["door", "window"]
    mark: Optional[str] = Field(None, description="The occurrence's own number/tag, if the model has one")
    type_mark: Optional[str] = None
    type_name: Optional[str] = None
    level: Optional[str] = None
    location: List[str] = Field(default_factory=list, description="Adjoining rooms/spaces, nearest first")
    leaves: Optional[int] = Field(None, ge=1, description="Door leaves in this assembly; a double door is 1 item, 2 leaves")
    width_m: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    duplicates: List[str] = Field(default_factory=list, description="Ids of identical symbols drawn on top, not counted")
    evidence_index: Optional[int] = Field(None, ge=0, description="Index into `evidence` of this item's marker")


class Answer(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    openings: List[OpeningItem] = Field(default_factory=list, description="Door/window inventory behind a count")
    path: str
    question: str
    region: Optional[Region] = None
    area_mode: Literal["whole_rooms", "intersection"] = "whole_rooms"
    room_areas: List[RoomArea] = Field(default_factory=list)
    slab_areas: List[SlabArea] = Field(default_factory=list)
    slab_groups: List[SlabGroup] = Field(default_factory=list)
    answer: Union[int, float, str, None] = Field(description="null when status is cannot_verify")
    unit: Optional[Unit] = Field(None, description="null for text answers")
    type: QuestionType
    status: Status
    confidence: float = Field(ge=0.0, le=1.0)
    source: Source = Field(description="Source whose value is reported in `answer`")
    evidence: List[Evidence] = Field(default_factory=list)
    explanation: Optional[str] = Field(None, description="Short human-readable reasoning / why it can't verify")
    sources: List[SourceAnswer] = Field(default_factory=list, description="Per-source answers when the router ran more than one")
    latency_ms: Optional[float] = None

    @model_validator(mode="after")
    def _consistent(self) -> "Answer":
        if self.status == Status.cannot_verify.value and self.answer is not None:
            raise ValueError("cannot_verify answers must have answer=null")
        if self.status != Status.cannot_verify.value and self.answer is None:
            raise ValueError("answer is null but status is not cannot_verify")
        if self.type == QuestionType.count.value and self.answer is not None:
            if isinstance(self.answer, str) or float(self.answer) != int(self.answer):
                raise ValueError("count answers must be integers")
        return self
