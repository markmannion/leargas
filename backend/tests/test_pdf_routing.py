"""PDF uploads: sheet-sized PDFs go to the sheet reader, small ones to Gemma via a rendered PNG twin."""
import sys
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for model.*

from app import router  # noqa: E402
from model.gemma_engine import image_for, pdf_png_twin  # noqa: E402


def _pdf(path: Path, w_pt: float, h_pt: float) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.draw_rect(fitz.Rect(20, 20, w_pt - 20, h_pt - 20))
    doc.save(path)
    doc.close()
    return path


def test_small_pdf_is_not_a_sheet(tmp_path):
    assert router._pdf_is_sheet(_pdf(tmp_path / "a4.pdf", 595, 842)) is False   # A4
    assert router._pdf_is_sheet(_pdf(tmp_path / "a3.pdf", 842, 1191)) is False  # A3


def test_large_pdf_is_a_sheet(tmp_path):
    assert router._pdf_is_sheet(_pdf(tmp_path / "a1.pdf", 1684, 2384)) is True  # A1
    assert router._pdf_is_sheet(_pdf(tmp_path / "a2.pdf", 1191, 1684)) is True  # A2 (just over)


def test_png_twin_rendered_once_and_found_by_both_sides(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "plan.pdf", 595, 842)
    twin = pdf_png_twin(pdf)
    assert twin == tmp_path / "plan.png" and twin.is_file()
    mtime = twin.stat().st_mtime_ns
    assert pdf_png_twin(pdf) == twin and twin.stat().st_mtime_ns == mtime  # reused, not re-rendered
    assert image_for(str(pdf)) == twin
    monkeypatch.setattr(router, "_abs", lambda rel: Path(rel))
    assert router.raster_image(str(pdf)) == twin


def test_router_renders_twin_for_a_fresh_pdf(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "upload.pdf", 595, 842)
    monkeypatch.setattr(router, "_abs", lambda rel: Path(rel))
    assert router.raster_image(str(pdf)) == tmp_path / "upload.png"
    assert (tmp_path / "upload.png").is_file()


def test_unreadable_pdf_gives_no_image(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert pdf_png_twin(bad) is None
