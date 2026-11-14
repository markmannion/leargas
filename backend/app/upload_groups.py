"""Drawing uploads, so a user (or a judge) can ask about their own sheet, not just the dataset's.

`POST /upload?name=<file name>[&group=<id>]`, body = the raw file bytes (no multipart, so no
python-multipart dependency). Returns `{"group": id, "drawing": <catalogue entry>}`.

Files land in `<data root>/uploads/<group>/<stem><ext>`, so the router and `/drawing` treat them
like dataset paths. Upload twins (plan.pdf + plan.dxf) with the same `group` and the same stem and
they pair up exactly like dataset twins: the DXF engine answers, Gemma reads the sheet, and the
router reconciles. The first upload picks the group (a content hash); pass it back for the rest.

An uploaded PDF gets page 1 rendered to a PNG twin when PyMuPDF is installed, because Gemma reads
raster images only.

`uploaded()` lists the uploads in `/drawings` format (one entry per stem, the most viewable file).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from . import drawings

router = APIRouter()

UPLOAD_DIR = "uploads"
MAX_BYTES = 60 * 1024 * 1024
# What each extension must start with. DXF is text with no fixed magic, so it's checked for a
# SECTION marker in the first few KB instead.
MAGIC = {
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8",),
    ".jpeg": (b"\xff\xd8",),
    ".pdf": (b"%PDF",),
    ".ifc": (b"ISO-10303-21",),
}
EXTS = (*MAGIC, ".dxf")
# Which file of a stem the viewer shows: the sheet the user uploaded beats the vector stand-in.
PRIMARY = {".pdf": 0, ".png": 1, ".jpg": 1, ".jpeg": 1, ".dxf": 2, ".ifc": 3}
GROUP_RE = re.compile(r"^[0-9a-f]{12}$")


def upload_root() -> Path:
    return drawings.data_root() / UPLOAD_DIR


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_")[:60]
    return stem or "drawing"


def _check(ext: str, body: bytes) -> None:
    if ext not in EXTS:
        raise HTTPException(415, f"unsupported file type {ext or '(none)'}; use {', '.join(EXTS)}")
    if not body:
        raise HTTPException(400, "empty file")
    if len(body) > MAX_BYTES:
        raise HTTPException(413, f"file is over {MAX_BYTES // (1024 * 1024)} MB")
    if ext == ".dxf":
        ok = b"SECTION" in body[:4096]
    else:
        ok = body.lstrip().startswith(MAGIC[ext])
    if not ok:
        raise HTTPException(415, f"file content doesn't look like {ext}")


def _pdf_png_twin(pdf: Path) -> Optional[Path]:
    """Render page 1 to `<stem>.png` beside the PDF (Gemma's input), or None without PyMuPDF."""
    try:
        import fitz
    except ImportError:
        return None
    out = pdf.with_suffix(".png")
    with fitz.open(pdf) as doc:
        if len(doc) == 0:
            raise HTTPException(400, "PDF has no pages")
        doc[0].get_pixmap(dpi=150).save(out)
    return out


def _entry(files: List[Path]) -> dict:
    """The catalogue entry for one uploaded stem: the most viewable of its files."""
    best = min(files, key=lambda p: PRIMARY.get(p.suffix.lower(), 9))
    rel = best.relative_to(drawings.data_root()).as_posix()
    return {
        "path": rel,
        "collection": UPLOAD_DIR,
        "name": best.stem,
        "render": drawings.render_kind(rel) or "none",
        "files": sorted(p.suffix.lower().lstrip(".") for p in files),
        "questions": [],
    }


def _stems(folder: Path) -> Dict[str, List[Path]]:
    out: Dict[str, List[Path]] = {}
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in EXTS:
            out.setdefault(p.stem, []).append(p)
    return out


def uploaded() -> List[dict]:
    """Every upload, newest group first, in `/drawings` format."""
    root = upload_root()
    if not root.is_dir():
        return []
    groups = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    return [_entry(files) for g in groups for files in _stems(g).values()]


@router.post("/upload")
async def upload(request: Request, name: str = Query(..., min_length=1, max_length=200),
                 group: Optional[str] = Query(None)) -> dict:
    ext = Path(name).suffix.lower()
    body = await request.body()
    _check(ext, body)
    if group is not None and not GROUP_RE.match(group):
        raise HTTPException(400, "bad group id")
    group = group or hashlib.sha1(body).hexdigest()[:12]
    folder = upload_root() / group
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{_safe_stem(name)}{ext}"
    dest.write_bytes(body)
    if ext == ".pdf":
        _pdf_png_twin(dest)
    return {"group": group, "drawing": _entry(_stems(folder)[dest.stem])}
