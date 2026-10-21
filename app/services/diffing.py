"""Lightweight text diffing used for change summaries and staleness magnitude."""

from __future__ import annotations

import difflib
import re

from app.textutil import normalize_text

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def line_diff(old: str, new: str, max_lines: int = 20) -> list[str]:
    """Return a compact unified-diff-ish list of changed lines."""
    old_lines = [l for l in old.split("\n") if l.strip()]
    new_lines = [l for l in new.split("\n") if l.strip()]
    out: list[str] = []
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        out.append(line)
        if len(out) >= max_lines:
            break
    return out


def change_magnitude(old: str, new: str) -> str:
    """Classify a change as ``none`` / ``minor`` / ``major``.

    The staleness *decision* is binary (hash differs => stale). Magnitude is an
    advisory signal so a user can triage: a numeric/clinical-parameter change
    (e.g. ``40 mmHg`` -> ``30 mmHg``) is ``major``; a wording tweak is ``minor``.
    """
    a, b = normalize_text(old), normalize_text(new)
    if a == b:
        return "none"
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    old_nums, new_nums = _NUMBER_RE.findall(a), _NUMBER_RE.findall(b)
    if old_nums != new_nums:
        return "major"
    if ratio < 0.6:
        return "major"
    return "minor"


def diff_summary(old: str, new: str) -> str:
    a, b = normalize_text(old), normalize_text(new)
    if a == b:
        return "no change"
    sm = difflib.SequenceMatcher(None, a, b)
    added = removed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    mag = change_magnitude(old, new)
    return f"{mag} change: +{added}/-{removed} chars"
