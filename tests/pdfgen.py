"""Build tiny synthetic PDFs so we can exercise parsing/matching edge cases
without hand-authoring fixtures. Headings are emitted in a bold font, which is
the signal the classifier keys on."""

from __future__ import annotations

from pathlib import Path

import pymupdf

# (text, is_heading) — headings are bold; body is regular
Sizes = {1: 16.5, 2: 12.9}


def make_pdf(path: Path, blocks: list[tuple[str, int]]) -> str:
    """``blocks`` is a list of (text, level) where level 0 = body paragraph,
    level 1..n = heading of that depth."""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72.0
    for text, level in blocks:
        if y > 760:
            page = doc.new_page()
            y = 72.0
        if level == 0:
            page.insert_text((72, y), text, fontsize=11, fontname="helv")
            y += 20
        else:
            page.insert_text(
                (72, y), text, fontsize=Sizes.get(level, 12.9),
                fontname="hebo",  # Helvetica-Bold -> detected as bold
            )
            y += 26
    doc.save(str(path))
    doc.close()
    return str(path)
