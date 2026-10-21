"""Regression guard: the exact shape of the reconstructed CT-200 tree (v1).

If a parser change alters any node's identity or parent, this fails loudly.
"""

from __future__ import annotations

from app.parsing.extract import extract
from app.parsing.hierarchy import parse
from tests.conftest import V1

EXPECTED_PAIRS = {
    ("title", None),
    ("1", "title"), ("1.1", "1"), ("1.2", "1"),
    ("2", "title"), ("2.1", "2"), ("2.1#table1", "2.1"), ("2.1.1.1", "2.1"), ("2.2", "2"),
    ("3", "title"), ("3.1", "3"), ("3.2", "3"), ("3.3", "3"), ("3.4", "3"),
    ("4", "title"), ("4.1", "4"), ("4.2", "4"), ("4.2#table1", "4.2"), ("4.3", "4"),
    ("5", "title"), ("5.1", "5"), ("5.2", "5"),
    ("6", "title"), ("6.1", "6"), ("6.2", "6"),
    ("7", "title"), ("7.1", "7"), ("7.2", "7"),
    ("8", "title"), ("8.1", "8"),
}


def test_full_tree_shape():
    result = parse(extract(V1))
    pairs = {(n.logical_key, n.parent_key) for n in result.nodes}
    assert pairs == EXPECTED_PAIRS
    assert len(result.nodes) == 30


def test_children_are_ordered_by_numeric_key():
    result = parse(extract(V1))
    kids = sorted(
        (n for n in result.nodes if n.parent_key == "3"), key=lambda n: n.sort_key
    )
    assert [n.logical_key for n in kids] == ["3.1", "3.2", "3.3", "3.4"]


def test_levels_are_derived_from_number_depth():
    result = parse(extract(V1))
    by_key = {n.logical_key: n for n in result.nodes}
    assert by_key["1"].level == 1
    assert by_key["1.1"].level == 2
    assert by_key["2.1.1.1"].level == 4  # depth, not font size
    assert by_key["3.2"].level == 2      # body-sized heading, still level 2
