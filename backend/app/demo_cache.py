"""Demo answer cache: stored `Answer`s served by `/ask` so the demo works with the model endpoint down.

Built by `backend/demo_cache.py`. Enabled with LEARGAS_DEMO_CACHE=1; the file is
LEARGAS_DEMO_CACHE_PATH (default data/demo_cache.json). A hit returns the stored answer unchanged
and the response carries `X-Leargas-Cache: hit`; a miss falls through to the live router.

Keys are (drawing path, question, engine), each normalized so trivial differences still hit:
paths use `/`, lose any prefix before `data/`; questions are NFKC, casefolded, whitespace-collapsed;
a missing engine means "auto".
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Tuple

from .drawings import REPO

DEFAULT_PATH = REPO / "data" / "demo_cache.json"
VERSION = 1

Key = Tuple[str, str, str]


def norm_path(p: str) -> str:
    p = p.strip().replace("\\", "/")
    i = p.find("data/")
    if i > 0 and p[i - 1] == "/":
        p = p[i:]
    while p.startswith("./"):
        p = p[2:]
    return p


def norm_question(q: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", q)).strip().casefold()


def norm_engine(e: Optional[str]) -> str:
    return (e or "auto").strip().lower()


def make_key(path: str, question: str, engine: Optional[str]) -> Key:
    return norm_path(path), norm_question(question), norm_engine(engine)


def key_str(k: Key) -> str:
    return "\t".join((k[2], k[0], k[1]))


def enabled() -> bool:
    return os.environ.get("LEARGAS_DEMO_CACHE", "").lower() in ("1", "true", "yes")


def cache_path() -> Path:
    p = os.environ.get("LEARGAS_DEMO_CACHE_PATH")
    return Path(p) if p else DEFAULT_PATH


def read(path: Path) -> dict:
    """The cache file as {"version", "entries": {key_str: {path, question, engine, answer, ...}}}."""
    if not path.exists():
        return {"version": VERSION, "entries": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("entries", {})
    return data


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


_loaded: Dict[str, Tuple[float, Dict[str, dict]]] = {}


def _entries(path: Path) -> Dict[str, dict]:
    """Entries of `path`, reloaded when the file changes (rebuild without restarting the server)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _loaded.get(str(path))
    if hit is None or hit[0] != mtime:
        try:
            hit = (mtime, read(path)["entries"])
        except (OSError, ValueError):
            hit = (mtime, {})
        _loaded[str(path)] = hit
    return hit[1]


def lookup(path: str, question: str, engine: Optional[str]) -> Optional[dict]:
    """The cached Answer JSON for this request, or None."""
    e = _entries(cache_path()).get(key_str(make_key(path, question, engine)))
    return None if e is None else e["answer"]
