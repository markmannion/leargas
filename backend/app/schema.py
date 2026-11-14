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
    mock = "mock"


class PolygonEvidence(BaseModel):
    kind: Literal["polygon"] = "polygon"
    points: List[Point] = Field(min_length=3)


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


class AskRequest(BaseModel):
    path: str = Field(description='Dataset path, e.g. "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"')
    question: str
    type: Optional[QuestionType] = Field(None, description="Hint if known; otherwise inferred")
    engine: Optional[Literal["auto", "geometry", "gemma_ft", "gemma_base"]] = "auto"


class SourceAnswer(BaseModel):
    """What an individual source said, kept so the UI can show agreement/disagreement."""

    source: Source
    answer: Union[int, float, str, None]
    unit: Optional[Unit] = None
    confidence: float = Field(ge=0.0, le=1.0)


class Answer(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    path: str
    question: str
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
