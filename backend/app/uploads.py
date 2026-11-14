"""Persist user plans alongside the dataset, independently of reference questions."""

from __future__ import annotations

import json
import re
import shutil
import uuid
import warnings
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from . import drawings

router = APIRouter()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".dxf"}
MAX_IMAGE_PIXELS = 40_000_000


def upload_root() -> Path:
    return drawings.data_root() / "data" / "uploads"


def catalogue() -> list[dict]:
    plans = []
    for manifest in sorted(upload_root().glob("*/plan.json"), reverse=True):
        if manifest.parent.name.startswith("."):
            continue
        try:
            plan = json.loads(manifest.read_text(encoding="utf-8"))
            if drawings._resolve(plan["path"]).is_file():
                plans.append(plan)
        except (OSError, ValueError, KeyError, HTTPException):
            continue
    return plans


def _validate(path: Path) -> str:
    """Decode before publishing. PDF page one also becomes the model's PNG twin."""
    try:
        if path.suffix == ".pdf":
            import fitz

            with fitz.open(path) as doc:
                if not doc.is_pdf or doc.needs_pass or not len(doc):
                    raise ValueError("PDF is empty or password protected")
                page = doc[0]
                scale = min(150 / 72, 6000 / max(page.rect.width, page.rect.height))
                if page.rect.width * page.rect.height * scale**2 > MAX_IMAGE_PIXELS:
                    raise ValueError("PDF page is too large")
                page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(path.with_suffix(".png"))
            return "pdf"
        if path.suffix == ".dxf":
            drawings._render_dxf(path)
            return "dxf"
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                expected = "PNG" if path.suffix == ".png" else "JPEG"
                if image.format != expected or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image format does not match its extension, or image is too large")
                image.verify()
            with Image.open(path) as image:
                image.load()
        return "image"
    except ImportError as exc:
        raise HTTPException(503, "Plan rendering is unavailable. Install the backend requirements and requirements-dxf.txt.") from exc
    except Exception as exc:
        raise HTTPException(400, "This plan could not be read. Upload a valid, unencrypted PDF, PNG, JPEG or DXF file.") from exc


@router.post("/drawings/upload", status_code=201)
async def upload(request: Request, filename: str = Query(..., min_length=1, max_length=255)) -> dict:
    """The request body is the original file bytes; filename is a query parameter."""
    name = Path(filename.replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Supported plan formats: PDF, PNG, JPEG and DXF.")
    name = (re.sub(r"[^\w .()-]", "_", Path(name).stem).strip(" .") or "Plan")[:120] + suffix
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Plans must be 25 MB or smaller.")
    identifier = uuid.uuid4().hex
    root = upload_root()
    pending = root / f".pending-{identifier}"
    try:
        pending.mkdir(parents=True)
        path = pending / name
        size = 0
        with path.open("xb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Plans must be 25 MB or smaller.")
                output.write(chunk)
        if not size:
            raise HTTPException(400, "The selected file is empty.")
        kind = await run_in_threadpool(_validate, path)
        plan = {
            "path": f"data/uploads/{identifier}/{name}",
            "name": Path(name).stem,
            "collection": "uploads",
            "render": kind,
            "questions": [],
        }
        (pending / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        pending.rename(root / identifier)
        return plan
    except OSError as exc:
        raise HTTPException(503, "The plan could not be saved. Check the server's drawing storage and try again.") from exc
    finally:
        shutil.rmtree(pending, ignore_errors=True)
