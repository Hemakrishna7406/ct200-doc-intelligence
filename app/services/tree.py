"""Subtree helpers.

A *container* node (a section that holds a table or subsections) has little or
no body text of its own — its real content lives in its children. So both
change detection and generation must operate on a node's **effective content**:
the node's own text followed by every descendant's text, in tree order.

This is why ``4.2 Error Codes`` correctly reports as *changed* when its error
code table gains a row, even though the heading text is untouched.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NodeVersion


def node_version_text(nv: NodeVersion) -> str:
    """Reconstruct the human-readable text of a node version (incl. tables).

    Lives here (not in ``generation``) so the browse/generation layers can both
    use it without a circular import.
    """
    parts = [nv.heading]
    if nv.body_text:
        parts.append(nv.body_text)
    if nv.table_json:
        for row in nv.table_json:
            parts.append(" | ".join((c or "") for c in row))
    return "\n".join(p for p in parts if p)


def _sort_key(nv: NodeVersion):
    if nv.number:
        return (0, tuple(int(x) for x in nv.number.split(".")))
    return (1, (nv.source_order,))


def subtree_node_versions(
    db: Session, node_id: int, version_id: int
) -> list[NodeVersion]:
    """The node's version plus all descendants, depth-first in tree order."""
    root = db.scalar(
        select(NodeVersion).where(
            NodeVersion.node_id == node_id,
            NodeVersion.document_version_id == version_id,
        )
    )
    if root is None:
        return []

    children_of: dict[int, list[NodeVersion]] = {}
    rows = db.scalars(
        select(NodeVersion).where(NodeVersion.document_version_id == version_id)
    )
    for nv in rows:
        if nv.parent_node_id is not None:
            children_of.setdefault(nv.parent_node_id, []).append(nv)

    out: list[NodeVersion] = []

    def walk(nv: NodeVersion) -> None:
        out.append(nv)
        kids = sorted(children_of.get(nv.node_id, []), key=_sort_key)
        for k in kids:
            walk(k)

    walk(root)
    return out
