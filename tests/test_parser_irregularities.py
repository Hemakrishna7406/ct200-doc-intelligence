"""Parser unit tests — one per structural irregularity in the CT-200 manual.

These run the extraction + hierarchy code directly, with no database, so a
failure points straight at the parser.
"""

from __future__ import annotations

from app.parsing.extract import extract
from app.parsing.hierarchy import node_content_hash, parse
from tests.conftest import V1

_result = parse(extract(V1))
_NODES = {n.logical_key: n for n in _result.nodes}


def test_multiline_title_is_assembled():
    """The title spans three lines; it must be one node, not three."""
    title = _NODES["title"]
    assert "CardioTrack CT-200 Home Blood" in title.heading
    assert "Pressure Monitor" in title.heading
    assert "User Manual" in title.heading


def test_out_of_order_sections_are_reordered_under_the_right_parent():
    """3.4 physically precedes 3.3 in the PDF. Both must be children of '3',
    and the tree must present 3.3 before 3.4."""
    assert _NODES["3.3"].parent_key == "3"
    assert _NODES["3.4"].parent_key == "3"
    assert _NODES["3.3"].sort_key < _NODES["3.4"].sort_key
    codes = {a["code"] for a in _result.anomalies}
    assert "out_of_order_section" in codes


def test_duplicate_heading_produces_two_distinct_nodes_with_correct_parents():
    """'Error Codes' appears as both 4.2 and 7.1 — two nodes, two parents."""
    assert _NODES["4.2"].heading == "Error Codes"
    assert _NODES["7.1"].heading == "Error Codes"
    assert _NODES["4.2"] is not _NODES["7.1"]
    assert _NODES["4.2"].parent_key == "4"
    assert _NODES["7.1"].parent_key == "7"
    dup = [a for a in _result.anomalies if a["code"] == "duplicate_heading_title"]
    assert dup and dup[0]["node_key"] == "7.1"


def test_skipped_level_is_reattached_and_flagged():
    """2.1.1.1 has no 2.1.1 parent; it must hang off 2.1 and be flagged."""
    assert _NODES["2.1.1.1"].level == 4
    assert _NODES["2.1.1.1"].parent_key == "2.1"
    codes = {a["code"] for a in _NODES["2.1.1.1"].anomalies}
    assert "skipped_level" in codes


def test_bold_numbered_list_items_are_not_mistaken_for_headings():
    """The classification list inside 3.3 ('1. Normal: ...') must stay body
    text, not become top-level sections."""
    assert "Normal:" in _NODES["3.3"].body_text
    assert not any(n.heading.startswith("Normal") for n in _result.nodes)
    # there is exactly one top-level section numbered 1
    assert _NODES["1"].heading == "Device Overview"


def test_tables_are_extracted_and_kept_out_of_body_text():
    """The spec table under 2.1 becomes its own table node; its cells must not
    leak into the section body."""
    tables = [n for n in _result.nodes if n.kind == "table"]
    assert tables, "expected at least one table node"
    spec = [t for t in tables if t.parent_key == "2.1"][0]
    assert spec.table[0] == ["Parameter", "Value"]
    assert len(spec.table) >= 8
    assert "Oscillometric" not in _NODES["2.1"].body_text


def test_page_break_continuity_is_preserved():
    """6.1's body continues onto the next page; the tail must not be lost."""
    assert "abrasive cleaners on the display" in _NODES["6.1"].body_text
    assert "Do not submerge" in _NODES["6.1"].body_text


def test_content_hash_covers_heading_and_body():
    n = _NODES["3.2"]
    original = node_content_hash(n)
    n2 = type(n)(
        logical_key=n.logical_key,
        number=n.number,
        heading="Renamed Heading",
        level=n.level,
        body_text=n.body_text,
    )
    assert node_content_hash(n2) != original
