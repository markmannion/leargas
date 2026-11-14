"""Drawing files and the drawing catalogue for the frontend.

`GET /drawing?path=...` serves the sheet image for a dataset path:
  1. the file itself if it is an image (png/jpg/svg) and exists locally;
  2. a PDF page rendered to PNG, if PyMuPDF is installed;
  3. otherwise the DXF twin (same stem) rendered to SVG with ezdxf, cached on disk.

Note: a DXF render is framed on the DXF extents, not on the PDF page, so evidence that is
normalized to the PDF will not line up exactly on it. It is a stand-in when the PDF is missing.

`GET /drawings` lists drawings that have questions and something renderable, with their questions.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

REPO = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parents[1] / ".cache" / "drawings"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}

router = APIRouter()


def data_root() -> Path:
    return Path(os.environ.get("LEARGAS_DATA_ROOT", REPO / "datasets" / "junction-dataset")).resolve()


def questions_path() -> Optional[Path]:
    p = os.environ.get("LEARGAS_QUESTIONS")
    p = Path(p) if p else data_root() / "questions.jsonl"
    return p if p.exists() else None


def _resolve(rel: str) -> Path:
    root = data_root()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise HTTPException(400, "path escapes the data root")
    return p


def _dxf_twin(p: Path) -> Optional[Path]:
    twin = p.with_suffix(".dxf")
    return twin if twin.exists() else None


def _renderable(rel: str) -> Optional[str]:
    """Which kind of sheet we can show for this path, or None."""
    p = _resolve(rel)
    if p.suffix.lower() in IMAGE_TYPES and p.exists():
        return "image"
    if p.suffix.lower() == ".pdf" and p.exists() and _has_fitz():
        return "pdf"
    if _dxf_twin(p):
        return "dxf"
    return None


@lru_cache(maxsize=1)
def _has_fitz() -> bool:
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        return False


def _render_pdf(p: Path, page: int) -> Path:
    out = CACHE / f"{p.stem}.p{page}.png"
    if not out.exists():
        import fitz

        out.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(p) as doc:
            if not 0 <= page < len(doc):
                raise HTTPException(404, "page out of range")
            doc[page].get_pixmap(dpi=150).save(out)
    return out


DXF_MARGIN = 1.5  # drawing units are metres, rendered 1 unit = 1 mm, so 1.5 m of paper


def _render_dxf(p: Path) -> Path:
    """Render a DXF to SVG, and record the framed region beside it (`<stem>.frame.json`)."""
    out = CACHE / f"{p.stem}.svg"
    frame = out.with_suffix(".frame.json")
    if not out.exists() or not frame.exists():
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg

        doc = ezdxf.readfile(p)
        backend = svg.SVGBackend()
        cfg = config.Configuration(
            background_policy=config.BackgroundPolicy.WHITE,
            color_policy=config.ColorPolicy.BLACK,
        )
        Frontend(RenderContext(doc), backend, config=cfg).draw_layout(doc.modelspace())
        bb = backend.player().bbox()
        page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(DXF_MARGIN))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(backend.get_string(page), encoding="utf-8")
        frame.write_text(json.dumps({"extmin": list(bb.extmin), "extmax": list(bb.extmax), "margin": DXF_MARGIN}))
    return out


def dxf_frame(dxf: Path) -> Dict[str, list]:
    """The DXF-coordinate region shown by the rendered sheet: content bbox plus margin."""
    _render_dxf(dxf)
    return json.loads((CACHE / f"{dxf.stem}.frame.json").read_text())


def render_kind(rel: str) -> Optional[str]:
    """"image" | "pdf" | "dxf" | None: what `GET /drawing` will serve for this path."""
    try:
        return _renderable(rel)
    except HTTPException:
        return None


@router.get("/drawing")
def drawing(path: str = Query(...), page: int = Query(0, ge=0)):
    p = _resolve(path)
    kind = _renderable(path)
    if kind == "image":
        return FileResponse(p, media_type=IMAGE_TYPES[p.suffix.lower()])
    if kind == "pdf":
        return FileResponse(_render_pdf(p, page), media_type="image/png")
    if kind == "dxf":
        return FileResponse(_render_dxf(_dxf_twin(p)), media_type="image/svg+xml",
                            headers={"X-Rendered-From": "dxf"})
    return Response(status_code=404, content=f"no local file or vector twin for {path}")


@lru_cache(maxsize=1)
def _catalogue() -> List[dict]:
    qp = questions_path()
    if qp is None:
        return []
    by_path: Dict[str, List[dict]] = defaultdict(list)
    with open(qp, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_path[r["path"]].append(
                {"question": r["question"], "answer": r["answer"], "unit": r["unit"], "type": r["type"]}
            )
    out = []
    for path, qs in sorted(by_path.items()):
        kind = _renderable(path)
        if kind is None:
            continue
        out.append({
            "path": path,
            "collection": path.split("/")[1] if path.count("/") >= 2 else "",
            "name": Path(path).stem,
            "render": kind,
            "questions": qs,
        })
    return out


@router.get("/drawings")
def drawings(limit: int = Query(300, ge=1, le=5000)) -> dict:
    cat = _catalogue()
    return {"total": len(cat), "drawings": cat[:limit]}
