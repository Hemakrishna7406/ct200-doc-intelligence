"""PDF extraction: text-layer lines + tables, with an OCR fallback.

Output is a flat, page-ordered list of :class:`Line` objects carrying the
typographic signals (size, boldness, position) that the hierarchy builder
needs, plus the tables found on each page. We deliberately keep this layer
dumb — it reports *what is on the page*, not what it means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from app.config import settings
from app.parsing import ocr as ocr_mod
from app.textutil import clean_text


@dataclass
class Line:
    text: str
    page: int  # 1-based
    order: int  # global reading order
    y0: float
    x0: float
    size: float
    bold: bool
    from_ocr: bool = False


@dataclass
class TableBlock:
    page: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str | None]]
    order: int


@dataclass
class PageInfo:
    page: int
    char_count: int
    used_ocr: bool
    ocr_engine: str | None = None


@dataclass
class ExtractionResult:
    lines: list[Line] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0


def _line_is_bold(spans: list[dict]) -> bool:
    for s in spans:
        font = (s.get("font") or "").lower()
        flags = s.get("flags", 0)
        if "bold" in font or (flags & 16):
            return True
    return False


def _dominant_size(spans: list[dict]) -> float:
    if not spans:
        return 0.0
    # weight by character count so a stray superscript does not dominate
    best, best_len = 0.0, -1
    for s in spans:
        n = len(s.get("text") or "")
        if n > best_len:
            best, best_len = s.get("size", 0.0), n
    return round(best, 1)


def _dedupe_tables(raw_tables: list[TableBlock]) -> list[TableBlock]:
    """PyMuPDF's find_tables over-detects: a real table plus spurious sub-tables
    inside it. Keep the largest tables and drop any whose bbox is contained in
    an already-kept table on the same page."""
    kept: list[TableBlock] = []

    def area(t: TableBlock) -> float:
        x0, y0, x1, y1 = t.bbox
        return max(0.0, x1 - x0) * max(0.0, y1 - y0)

    for t in sorted(raw_tables, key=area, reverse=True):
        if len(t.rows) < 2 or len(t.rows[0]) < 2:
            continue  # a real table has >=2 rows and >=2 cols
        x0, y0, x1, y1 = t.bbox
        contained = False
        for k in kept:
            kx0, ky0, kx1, ky1 = k.bbox
            if x0 >= kx0 - 2 and y0 >= ky0 - 2 and x1 <= kx1 + 2 and y1 <= ky1 + 2:
                contained = True
                break
        if not contained:
            kept.append(t)
    kept.sort(key=lambda t: (t.page, t.bbox[1]))
    return kept


def _tables_on_page(doc_page: pymupdf.Page, page_no: int) -> list[TableBlock]:
    out: list[TableBlock] = []
    try:
        found = doc_page.find_tables()
    except Exception:  # pragma: no cover - defensive
        return out
    for t in found.tables:
        try:
            rows = t.extract()
        except Exception:  # pragma: no cover
            continue
        rows = [
            [None if c is None else clean_text(c.replace("\n", " ")) for c in row]
            for row in rows
        ]
        out.append(TableBlock(page=page_no, bbox=tuple(t.bbox), rows=rows, order=0))
    return out


def extract(path: str) -> ExtractionResult:
    """Extract lines + tables from ``path`` (a PDF)."""
    result = ExtractionResult()
    doc = pymupdf.open(path)
    result.page_count = doc.page_count

    order = 0
    raw_tables: list[TableBlock] = []

    for pno in range(doc.page_count):
        page = doc[pno]
        page_no = pno + 1
        d = page.get_text("dict")
        page_char_count = 0

        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = clean_text("".join(s.get("text", "") for s in spans))
                if not text:
                    continue
                page_char_count += len(text)
                x0, y0 = line["bbox"][0], line["bbox"][1]
                result.lines.append(
                    Line(
                        text=text,
                        page=page_no,
                        order=order,
                        y0=round(y0, 1),
                        x0=round(x0, 1),
                        size=_dominant_size(spans),
                        bold=_line_is_bold(spans),
                    )
                )
                order += 1

        raw_tables.extend(_tables_on_page(page, page_no))

        used_ocr = False
        engine = None
        if page_char_count < settings.ocr_min_chars_per_page and settings.ocr_enabled:
            if ocr_mod.available():
                pix = page.get_pixmap(dpi=settings.ocr_dpi)
                res = ocr_mod.ocr_png_bytes(pix.tobytes("png"))
                engine = res.engine
                used_ocr = True
                for i, raw in enumerate(res.text.splitlines()):
                    if raw.strip():
                        result.lines.append(
                            Line(
                                text=raw.strip(),
                                page=page_no,
                                order=order,
                                y0=float(i * 10),
                                x0=0.0,
                                size=0.0,
                                bold=False,
                                from_ocr=True,
                            )
                        )
                        order += 1
            else:
                result.warnings.append(
                    f"page {page_no}: only {page_char_count} chars and no OCR "
                    "engine available — content may be missing"
                )

        result.pages.append(
            PageInfo(
                page=page_no,
                char_count=page_char_count,
                used_ocr=used_ocr,
                ocr_engine=engine,
            )
        )

    result.tables = _dedupe_tables(raw_tables)
    # assign table reading order
    for i, t in enumerate(result.tables):
        t.order = i
    doc.close()
    return result
