"""Router: answer one question about one drawing from every source that applies, then reconcile.

Sources
  geometry  DXF twin (Swiss dwellings) or IFC model (ifc_models plans and .ifc files). The question
            is parsed to a structured `Query` first; the engines never see the question text.
  gemma     the raster model behind MODEL_BASE_URL (Mark's infra/model_proxy.py), on the drawing's image.

engine="auto" runs geometry and fine-tuned Gemma together when both apply:
  - both answer and agree (count exact, quantities within AGREE_TOL) -> verified, geometry's value
  - both answer and differ -> disagreement, geometry's value reported, both listed in `sources`
  - one answers -> geometry is verified; Gemma is verified/partial by its own confidence
  - neither is confident -> cannot_verify, with each source's reason
engine="geometry" | "gemma_ft" | "gemma_base" runs only that source.

Evidence: DXF items become polygons normalized to the rendered DXF sheet (`/drawing` serves that
render when there is no local PDF/PNG). Gemma's points are already normalized to its input image.
IFC answers carry no image evidence yet.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Union

from . import drawings
from .query.parser import parse
from .query.schema import Query
from .schema import (
    Answer,
    AskRequest,
    Evidence,
    PointEvidence,
    PolygonEvidence,
    QuestionType,
    Source,
    SourceAnswer,
    Status,
)

AGREE_TOL = 0.02  # relative, matches the official scoring tolerance
GEOMETRY_CONFIDENCE = 0.95
# gemma-base is ~93% right at confidence >= 0.99 but only ~58% at 0.8-0.95 (957 held-out answers,
# results/calibration_gemma-base.json), so anything lower lets wrong answers through as verified.
GEMMA_VERIFIED = float(os.environ.get("LEARGAS_GEMMA_VERIFIED", 0.99))
GEMMA_PARTIAL = float(os.environ.get("LEARGAS_GEMMA_PARTIAL", 0.5))
GEMMA_TIMEOUT = float(os.environ.get("LEARGAS_GEMMA_TIMEOUT", 60))
# Run 1 and every baseline were prompted without the points addendum; only a model trained with
# points (run 2) should get it.
GEMMA_POINTS = os.environ.get("LEARGAS_GEMMA_POINTS", "0") == "1"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")

_pool = ThreadPoolExecutor(max_workers=8)


@dataclass
class Outcome:
    """What one source said. `value is None` means it could not answer; `reason` says why."""

    source: Source
    value: Union[int, float, str, None] = None
    unit: Optional[str] = None
    confidence: float = 0.0
    evidence: List[Evidence] = field(default_factory=list)
    explanation: Optional[str] = None
    reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.value is not None


# ------------------------------------------------------------------------------------ sources

def _abs(rel: str) -> Path:
    return drawings.data_root() / rel


def dxf_twin(rel: str) -> Optional[Path]:
    p = _abs(rel).with_suffix(".dxf")
    return p if p.is_file() else None


def ifc_model(rel: str) -> Optional[Path]:
    if "/ifc_models/" not in f"/{rel}" and not rel.lower().endswith(".ifc"):
        return None
    from .ifc import CannotVerify, resolve_model

    try:
        return resolve_model(_abs(rel))
    except CannotVerify:
        return None


def raster_image(rel: str) -> Optional[Path]:
    """The image Gemma looks at: the file itself, or its same-stem PNG twin (Swiss PDFs have one)."""
    p = _abs(rel)
    if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file():
        return p
    twin = p.with_suffix(".png")
    return twin if twin.is_file() else None


@lru_cache(maxsize=64)
def _dxf_drawing(dxf: str):
    from .dxf import parse_dxf

    return parse_dxf(dxf)


def _dxf_evidence(rel: str, dxf: Path, drawing, item_ids: List[str]) -> List[Evidence]:
    if drawings.render_kind(rel) != "dxf":
        return []  # the sheet shown is a PDF/PNG; aligning DXF onto it is not done yet
    fr = drawings.dxf_frame(dxf)
    (x0, y0), (x1, y1), m = fr["extmin"], fr["extmax"], fr["margin"]
    w, h = (x1 - x0) + 2 * m, (y1 - y0) + 2 * m

    def norm(x: float, y: float):
        return (min(max((x - x0 + m) / w, 0.0), 1.0), min(max((y1 - y + m) / h, 0.0), 1.0))

    by_id = {i.id: i for i in drawing.items}
    out = []
    for iid in item_ids:
        it = by_id.get(iid)
        if it is None or len(it.points) < 3:
            continue
        label = " ".join(s for s in (it.room_id, it.label) if s) or it.kind
        value = it.printed_area_m2 if it.printed_area_m2 is not None else it.geometric_area_m2
        if it.kind == "room" and value is not None:
            label = f"{label} {value:g} m²"
        out.append(Evidence(
            shape=PolygonEvidence(points=[norm(x, y) for x, y in it.points]),
            label=label,
            value=value if it.kind == "room" else None,
            source=Source.geometry_dxf,
        ))
    return out


def run_dxf(rel: str, dxf: Path, q: Optional[Query], parse_reason: Optional[str]) -> Outcome:
    out = Outcome(Source.geometry_dxf)
    if q is None:
        out.reason = f"Question not understood as a geometry query ({parse_reason or 'no parse'})."
        return out
    from .dxf import CannotVerify
    from .query.adapters import to_dxf

    dq = to_dxf(q)
    if dq is None:
        out.reason = f"The DXF engine can't express {q.op} of {q.target} with these filters."
        return out
    try:
        drawing = _dxf_drawing(str(dxf))
        r = drawing.query(dq)
    except CannotVerify as e:
        out.reason = f"DXF: {e}"
        return out
    except Exception as e:  # malformed file etc.: never crash the request
        out.reason = f"DXF engine error: {type(e).__name__}: {e}"
        return out
    out.value, out.unit, out.confidence = r.value, r.unit, GEOMETRY_CONFIDENCE
    out.explanation = r.explanation
    try:
        out.evidence = _dxf_evidence(rel, dxf, drawing, r.item_ids)
    except Exception:
        out.evidence = []  # evidence is best effort; the answer stands without it
    return out


def run_ifc(model: Path, q: Optional[Query], parse_reason: Optional[str]) -> Outcome:
    out = Outcome(Source.geometry_ifc)
    if q is None:
        out.reason = f"Question not understood as a geometry query ({parse_reason or 'no parse'})."
        return out
    from .ifc import CannotVerify, open_model

    try:
        r = open_model(str(model)).query(q)
    except CannotVerify as e:
        out.reason = f"IFC: {e}"
        return out
    except Exception as e:
        out.reason = f"IFC engine error: {type(e).__name__}: {e}"
        return out
    out.value, out.unit, out.confidence = r.value, r.unit, GEOMETRY_CONFIDENCE
    out.explanation = r.explanation
    return out


def gemma_available() -> bool:
    _import_model_pkg()
    return bool(os.environ.get("MODEL_BASE_URL"))


@lru_cache(maxsize=1)
def _import_model_pkg():
    repo = str(drawings.REPO)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        from model import client  # noqa: F401  (loads .env into the environment)

        return client
    except Exception:
        return None


def run_gemma(source: Source, image: Optional[Path], question: str) -> Outcome:
    out = Outcome(source)
    if image is None:
        out.reason = "No raster image of this drawing is available for the model."
        return out
    client = _import_model_pkg()
    if client is None or not os.environ.get("MODEL_BASE_URL"):
        out.reason = "Model endpoint not configured (MODEL_BASE_URL)."
        return out
    name = "gemma-ft" if source == Source.gemma_ft else "gemma-base"
    try:
        r = client.ask(str(image), question, model=name, with_points=GEMMA_POINTS, timeout=GEMMA_TIMEOUT)
    except Exception as e:
        out.reason = f"{name} request failed: {e}"
        return out
    if not r.get("ok") or r.get("abstained") or r.get("answer") is None:
        out.reason = f"{name} abstained" + (f": {r['reason']}" if r.get("reason") else ".")
        return out
    out.value, out.unit = r["answer"], r.get("unit")
    out.confidence = float(r["confidence"]) if r.get("confidence") is not None else GEMMA_PARTIAL
    out.explanation = f"{name} read it from the image" + (f": {r['reason']}" if r.get("reason") else ".")
    out.evidence = [
        Evidence(shape=PointEvidence(point=(x, y)), label=f"{name} point", source=source)
        for x, y in (r.get("points") or [])
    ]
    return out


# ------------------------------------------------------------------------------------ reconcile

def _guess_type(question: str) -> QuestionType:
    """Keyword fallback for the answer type when the question didn't parse."""
    q = question.lower()
    if any(k in q for k in ("m²", "m2", "area", "fläche", "pinta-ala", "areal", "surface")):
        return QuestionType.area
    if any(k in q for k in ("m³", "m3", "volume", "volumen")):
        return QuestionType.volume
    if any(k in q for k in ("length", "metres", "meters", "länge", "længde")):
        return QuestionType.length
    return QuestionType.count


def _qtype(q: Optional[Query], req: AskRequest, value) -> QuestionType:
    if req.type:
        return QuestionType(req.type)
    if q is not None:
        return QuestionType(q.op)
    if isinstance(value, str):
        return QuestionType.text
    return _guess_type(req.question)


def _unit(u: Optional[str], qtype: QuestionType) -> Optional[str]:
    if qtype == QuestionType.text:
        return None
    if u in ("count", "m", "m2", "m3", "ft", "ft2", "ft3"):
        return u
    return {QuestionType.count: "count", QuestionType.area: "m2",
            QuestionType.length: "m", QuestionType.volume: "m3"}.get(qtype)


def _value(v, qtype: QuestionType):
    if qtype == QuestionType.count and isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(round(v))
    return v


def agree(a: Outcome, b: Outcome) -> bool:
    try:
        x, y = float(a.value), float(b.value)
    except (TypeError, ValueError):
        return str(a.value).strip().casefold() == str(b.value).strip().casefold()
    if a.unit == "count" or b.unit == "count":
        return round(x) == round(y)
    return abs(x - y) <= AGREE_TOL * max(abs(x), abs(y), 1e-9)


def _source_answer(o: Outcome, qtype: QuestionType) -> SourceAnswer:
    return SourceAnswer(source=o.source, answer=_value(o.value, qtype) if o.ok else None,
                        unit=_unit(o.unit, qtype) if o.ok else None, confidence=o.confidence if o.ok else 0.0)


def reconcile(req: AskRequest, q: Optional[Query], outcomes: List[Outcome]) -> dict:
    geo = next((o for o in outcomes if o.source in (Source.geometry_dxf, Source.geometry_ifc)), None)
    gem = next((o for o in outcomes if o.source in (Source.gemma_ft, Source.gemma_base)), None)
    first = next((o for o in outcomes if o.ok), None)
    qtype = _qtype(q, req, first.value if first else None)
    sources = [_source_answer(o, qtype) for o in outcomes] if len(outcomes) > 1 else []

    def answer(o: Outcome, status: Status, conf: float, explanation: str, evidence=None) -> dict:
        return dict(answer=_value(o.value, qtype), unit=_unit(o.unit, qtype), type=qtype, status=status,
                    confidence=conf, source=o.source, evidence=o.evidence if evidence is None else evidence,
                    explanation=explanation, sources=sources)

    if geo and geo.ok and gem and gem.ok:
        if agree(geo, gem):
            return answer(geo, Status.verified, max(geo.confidence, 0.99),
                          f"{geo.explanation} The model agrees ({_value(gem.value, qtype)}).",
                          geo.evidence + gem.evidence)
        return answer(geo, Status.disagreement, 0.5,
                      f"{geo.explanation} The model says {_value(gem.value, qtype)} instead; check the drawing.",
                      geo.evidence + gem.evidence)
    if geo and geo.ok:
        note = f" ({gem.reason})" if gem and gem.reason else ""
        return answer(geo, Status.verified, geo.confidence, f"{geo.explanation}{note}")
    if gem and gem.ok:
        note = f" Geometry could not check it: {geo.reason}" if geo and geo.reason else ""
        if gem.confidence >= GEMMA_VERIFIED:
            return answer(gem, Status.verified, gem.confidence, f"{gem.explanation}{note}")
        if gem.confidence >= GEMMA_PARTIAL:
            return answer(gem, Status.partial, gem.confidence, f"{gem.explanation} Low confidence.{note}")
        reasons = [f"{gem.source.value} answered {gem.value} with low confidence ({gem.confidence:.2f})."]
    else:
        reasons = []
    reasons += [o.reason for o in outcomes if o.reason]
    src = outcomes[0].source if outcomes else Source.geometry_dxf
    return dict(answer=None, unit=None, type=qtype, status=Status.cannot_verify, confidence=0.0, source=src,
                evidence=[], explanation=" ".join(reasons) or "No source can answer this drawing.", sources=sources)


# ------------------------------------------------------------------------------------ entry point

def _area_unprinted(req: AskRequest, q: Optional[Query]) -> bool:
    """Area question on a swiss render that prints no m² (gemma-base: 0/68). The DXF still answers."""
    if _qtype(q, req, None) != QuestionType.area or _import_model_pkg() is None:
        return False
    from model import common

    return common.prints_areas(req.path) is False


def route(req: AskRequest) -> Answer:
    t0 = time.perf_counter()
    engine = req.engine or "auto"
    dxf = dxf_twin(req.path)
    ifc = None if dxf else ifc_model(req.path)
    image = raster_image(req.path)

    want_geo = engine in ("auto", "geometry")
    gemma_src = {"gemma_ft": Source.gemma_ft, "gemma_base": Source.gemma_base}.get(engine)
    if engine == "auto" and gemma_available():
        gemma_src = Source.gemma_ft

    jobs = []
    if gemma_src is not None:
        jobs.append(_pool.submit(run_gemma, gemma_src, image, req.question))

    outcomes: List[Outcome] = []
    q = None
    if want_geo:
        if dxf or ifc:
            pr = parse(req.question)
            q = pr.query
            outcomes.append(run_dxf(req.path, dxf, q, pr.reason) if dxf else run_ifc(ifc, q, pr.reason))
        elif engine == "geometry" or gemma_src is None:
            outcomes.append(Outcome(Source.geometry_dxf, reason="No DXF or IFC twin for this drawing."))
    elif engine in ("gemma_ft", "gemma_base"):
        q = parse(req.question, use_llm=False).query  # only for the answer type

    outcomes += [j.result() for j in jobs]
    if jobs and _area_unprinted(req, q):
        outcomes = [
            Outcome(o.source, reason="This sheet prints no room areas, so the model can't read one off the image.")
            if o.source in (Source.gemma_ft, Source.gemma_base) else o
            for o in outcomes
        ]
    if engine == "auto" and gemma_src is None and not (dxf or ifc):
        outcomes.append(Outcome(Source.gemma_ft, reason="Model endpoint not configured (MODEL_BASE_URL)."))

    fields = reconcile(req, q, outcomes)
    return Answer(path=req.path, question=req.question, latency_ms=(time.perf_counter() - t0) * 1000, **fields)
