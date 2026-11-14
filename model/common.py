"""Shared helpers for Mark's track: dataset paths, question loading, drawing groups, templates.

Paths in questions.jsonl look like ``data/<source>/<file>`` and are relative to the dataset
root (``datasets/junction-dataset`` by default, override with the JUNCTION_DATA env var).

Stdlib only, so Harry can import it without installing anything.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_ROOT = Path(os.environ.get("JUNCTION_DATA", REPO_ROOT / "datasets" / "junction-dataset"))
QUESTIONS_PATH = DATASET_ROOT / "questions.jsonl"
SPLITS_DIR = REPO_ROOT / "data" / "splits"
HELDOUT_PATH = SPLITS_DIR / "heldout_drawings.txt"

# Sources whose questions are answered from pixels by Gemma (the raster track).
# swiss_dwellings questions point at the PDF, but every PDF has a PNG twin with the same stem.
RASTER_SOURCES = ("cubicasa5k", "swiss_dwellings")
# Sources with drawings but no questions at all (judge-style / demo use only).
UNLABELLED_SOURCES = ("habs", "finna", "europeana", "wikimedia")


def source_of(path: str) -> str:
    """'data/cubicasa5k/colorful-10052.png' -> 'cubicasa5k'."""
    parts = path.replace("\\", "/").split("/")
    return parts[1] if parts[0] == "data" else parts[0]


def abs_path(path: str) -> Path:
    """Dataset-relative path ('data/...') -> absolute path on disk."""
    return DATASET_ROOT / path


def stem_path(path: str) -> str:
    """Path without extension: twins (pdf/dxf/png/svg) share it."""
    return path.rsplit(".", 1)[0]


@lru_cache(maxsize=1)
def _ifc_model_stems() -> tuple[str, ...]:
    d = DATASET_ROOT / "data" / "ifc_models"
    if not d.exists():
        return ()
    return tuple(sorted((p.stem for p in d.glob("*.ifc")), key=len, reverse=True))


def group_key(path: str) -> str:
    """The unit we split on. Everything that shows the same drawing/model shares a key.

    - swiss_dwellings / cubicasa5k / most sources: the file stem (pdf, dxf, png twins collapse).
    - ifc_models: the parent IFC model. Plans/sections are rendered from ``<model>.ifc`` and named
      ``<model>_<view>.pdf``, so all views of one building land on the same side of the split.
    - opening_design: the project folder (first path component under the source).
    """
    path = path.replace("\\", "/")
    src = source_of(path)
    rel = path.split("/", 2)[2] if path.startswith("data/") else path.split("/", 1)[1]
    if src == "ifc_models":
        stem = Path(rel).stem
        for m in _ifc_model_stems():  # longest first
            if stem == m or stem.startswith(m + "_"):
                return f"ifc_models/{m}"
        # resbim-<n>_plan.png style files have their model as the part before "_plan"
        return f"ifc_models/{stem.split('_plan')[0]}"
    if src == "opening_design":
        return f"opening_design/{rel.split('/', 1)[0]}"
    return f"{src}/{Path(rel).stem}"


def load_questions(path: Path | None = None) -> list[dict]:
    path = path or QUESTIONS_PATH
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@lru_cache(maxsize=1)
def heldout_groups() -> frozenset[str]:
    """Group keys of every held-out drawing (from data/splits/heldout_drawings.txt)."""
    if not HELDOUT_PATH.exists():
        raise FileNotFoundError(f"{HELDOUT_PATH} missing; run python -m model.make_split")
    keys = set()
    for line in HELDOUT_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.add(group_key(line))
    return frozenset(keys)


def is_heldout(path: str) -> bool:
    """True if this drawing (or any twin / sibling view of it) is in the held-out split."""
    return group_key(path) in heldout_groups()


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def template_of(question: str) -> str:
    """Coarse template: digits replaced by '#'. Room names in quotes are kept on purpose,
    since 'How many rooms labelled Küche' and '... Bad' have very different answer priors."""
    return _NUM.sub("#", question.strip())


_LANG_HINTS = [  # checked in order; covers every language in questions.jsonl plus sv for the judge set
    ("fi", re.compile(r"^\s*(kuinka|montako|paljonko|onko|mikä|mitä)\b|\bpohjapiirustu", re.I)),
    ("sv", re.compile(r"^\s*(hur|vilken|vad)\b|\b(planritning|våning)", re.I)),
    ("da", re.compile(r"^\s*(hvad|hvor mange|hvilk)", re.I)),
    ("nl", re.compile(r"^\s*(wat is|hoeveel|welke)\b", re.I)),
    ("de", re.compile(r"^\s*(wie|welche|was ist)\b|\b(grundriss|geschoss|eingezeichnet)\b", re.I)),
    ("et", re.compile(r"^\s*(kui suur|mitu)\b", re.I)),
    ("pl", re.compile(r"^\s*(ile|jaka|jaki)\b", re.I)),
    ("ro", re.compile(r"^\s*(care este|câte|câți)\b", re.I)),
    ("it", re.compile(r"^\s*(quant[ieoa]|qual è|qual e')\b|^\s*qual\s+è", re.I)),
    ("es", re.compile(r"^\s*¿|^\s*(cuál|cuántos|cuántas)\b", re.I)),
    ("fr", re.compile(r"^\s*(combien|quelle|quel|quelles|quels)\b", re.I)),
]


def guess_lang(question: str) -> str:
    """Cheap language tag for balancing and reporting. Defaults to 'en'."""
    for lang, rx in _LANG_HINTS:
        if rx.search(question):
            return lang
    return "en"


_PRINTED_AREAS_CACHE = SPLITS_DIR / "swiss_printed_areas.json"


@lru_cache(maxsize=1)
def swiss_printed_areas() -> dict[str, bool]:
    """{swiss stem: True if the drawing prints room areas (m²) on the plan}.

    Only ~1 in 4 swiss renders print "12.34 m²" under each room; the rest show names and numbers
    only. Area questions on the others can't be read off the pixels (the geometry engine still
    answers them from the DXF). Detected from the DXF text; cached in data/splits/."""
    if _PRINTED_AREAS_CACHE.exists():
        return json.loads(_PRINTED_AREAS_CACHE.read_text(encoding="utf-8"))
    out = {}
    for p in sorted((DATASET_ROOT / "data" / "swiss_dwellings").glob("*.dxf")):
        b = p.read_bytes()
        out[p.stem] = (b"m\xc2\xb2" in b) or (b"\\U+00B2" in b)
    _PRINTED_AREAS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _PRINTED_AREAS_CACHE.write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    return out


def prints_areas(path: str) -> bool | None:
    """True/False for swiss drawings, None for other sources."""
    if source_of(path) != "swiss_dwellings":
        return None
    return swiss_printed_areas().get(Path(path).stem)
