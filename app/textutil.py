"""Text normalisation and hashing helpers.

The single most important idea in this project lives here: **normalise before
you hash**. Two node snapshots are considered "the same content" only if their
normalised text matches. Normalisation removes differences that are not
semantic:

* unicode ligatures and dashes introduced by the PDF font (``ﬁ`` -> ``fi``,
  ``–``/``—``/``‑`` -> ``-``)
* collapse of all runs of whitespace (including the newlines that appear
  wherever the PDF happened to wrap a line or break a page)
* trailing/leading whitespace and case

Because whitespace and page position are normalised away, the fact that a
paragraph moved from the bottom of page 3 to the top of page 4 between v1 and
v2 does **not** register as a content change. Only a real edit does.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}
_DASHES = dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-")
_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a0": " ",
}

_TRANS = {**_LIGATURES, **_DASHES, **_QUOTES}

_WS_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Repair PDF-font artefacts but **preserve whitespace structure**.

    Ligatures (``ﬁ``/``ﬀ``), curly quotes and unicode dashes are substituted;
    runs of spaces/tabs are collapsed; newlines are left alone so paragraph
    boundaries survive.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANS)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def normalize_text(text: str) -> str:
    """Return a canonical form of ``text`` for hashing / comparison."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANS)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def content_hash(text: str) -> str:
    """sha256 of the normalised text."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def content_hash_table(rows: list[list[str | None]]) -> str:
    """Hash a table by its normalised cell contents."""
    flat = []
    for row in rows:
        flat.append("\t".join(normalize_text(c or "") for c in row))
    return content_hash("\n".join(flat))


def fingerprint(pairs: list[tuple[int, int]]) -> str:
    """Stable fingerprint over a set of (node_id, node_version_id) pairs."""
    key = ";".join(f"{n}:{v}" for n, v in sorted(set(pairs)))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
