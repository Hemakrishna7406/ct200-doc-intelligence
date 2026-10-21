"""OCR fallback: an image-only page must be flagged when no engine is present,
and must actually be OCR'd when one is."""

from __future__ import annotations

import pymupdf

from app.parsing import ocr as ocr_mod
from app.parsing.extract import extract
from tests.conftest import DOCROOT


def _image_only_pdf(name: str) -> str:
    path = DOCROOT / name
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(100, 100, 400, 200), fill=(0.2, 0.2, 0.2))
    doc.save(str(path))
    doc.close()
    return str(path)


def test_image_only_page_is_flagged_without_ocr_engine(monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: False)
    res = extract(_image_only_pdf("scan_no_engine.pdf"))
    assert res.pages[0].char_count == 0
    assert res.pages[0].used_ocr is False
    assert any("no OCR engine" in w for w in res.warnings)


def test_image_only_page_is_ocred_when_engine_present(monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: True)
    monkeypatch.setattr(
        ocr_mod,
        "ocr_png_bytes",
        lambda png, lang="eng": ocr_mod.OcrResult(text="1. Device Overview", engine="fake"),
    )
    res = extract(_image_only_pdf("scan_with_engine.pdf"))
    assert res.pages[0].used_ocr is True
    assert res.pages[0].ocr_engine == "fake"
    assert any(ln.from_ocr for ln in res.lines)
    assert not res.warnings
