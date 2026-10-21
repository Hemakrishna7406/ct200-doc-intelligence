"""OCR adapter.

The assignment calls for an "OCR-based" pipeline. In practice the CT-200 PDFs
carry a real text layer, so the pipeline is **text-layer first** and falls back
to OCR only for pages that look image-only. This module isolates the OCR
dependency so the rest of the code does not care which engine is present.

Availability is probed at import time. If ``pytesseract`` or the ``tesseract``
binary is missing, ``available()`` returns False and the extractor records an
explicit warning for any page it could not read — we would rather expose an
unsupported page than silently emit empty content.
"""

from __future__ import annotations

import io
import shutil
from dataclasses import dataclass

try:  # pragma: no cover - environment dependent
    import pytesseract
    from PIL import Image

    _PYTESS = True
except Exception:  # pragma: no cover
    _PYTESS = False


@dataclass
class OcrResult:
    text: str
    engine: str


def available() -> bool:
    """True only if a working OCR engine is present."""
    if not _PYTESS:
        return False
    return shutil.which("tesseract") is not None


def engine_name() -> str:
    return "tesseract" if available() else "none"


def ocr_png_bytes(png_bytes: bytes, lang: str = "eng") -> OcrResult:
    """Run OCR over raw PNG bytes. Raises RuntimeError if no engine is present."""
    if not available():
        raise RuntimeError(
            "OCR requested but no engine is available (install `tesseract` "
            "and `pytesseract`)."
        )
    image = Image.open(io.BytesIO(png_bytes))
    text = pytesseract.image_to_string(image, lang=lang)
    return OcrResult(text=text, engine="tesseract")
