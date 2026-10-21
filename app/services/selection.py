"""Selections: named, version-pinned sets of node versions.

A selection stores ``(node_id, node_version_id, content_hash)`` for every member.
Pinning the *version* is what lets an old selection keep resolving to the exact
text it was created against, even after the document is re-ingested.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentVersion, Node, NodeVersion, Selection, SelectionItem
from app.textutil import fingerprint


class SelectionError(ValueError):
    pass


def _resolve_version(db: Session, document_id: int, version_no: int | None) -> DocumentVersion:
    q = select(DocumentVersion).where(DocumentVersion.document_id == document_id)
    if version_no is not None:
        q = q.where(DocumentVersion.version_no == version_no)
    else:
        q = q.order_by(DocumentVersion.version_no.desc())
    dv = db.scalar(q.limit(1))
    if dv is None:
        raise SelectionError(
            f"no version found for document {document_id} (version_no={version_no})"
        )
    return dv


def create_selection(
    db: Session, name: str, node_ids: list[int], version_no: int | None = None
) -> Selection:
    if not node_ids:
        raise SelectionError("a selection needs at least one node")

    nodes = list(db.scalars(select(Node).where(Node.id.in_(node_ids))))
    if len(nodes) != len(set(node_ids)):
        found = {n.id for n in nodes}
        missing = sorted(set(node_ids) - found)
        raise SelectionError(f"unknown node ids: {missing}")

    document_ids = {n.document_id for n in nodes}
    if len(document_ids) != 1:
        raise SelectionError("all nodes in a selection must belong to one document")
    document_id = document_ids.pop()

    dv = _resolve_version(db, document_id, version_no)

    items: list[SelectionItem] = []
    pairs: list[tuple[int, int]] = []
    for node in nodes:
        nv = db.scalar(
            select(NodeVersion).where(
                NodeVersion.node_id == node.id,
                NodeVersion.document_version_id == dv.id,
            )
        )
        if nv is None:
            raise SelectionError(
                f"node {node.id} ({node.logical_key}) does not exist in version "
                f"{dv.version_no}"
            )
        pairs.append((node.id, nv.id))
        items.append(
            SelectionItem(
                node_id=node.id, node_version_id=nv.id, content_hash=nv.content_hash
            )
        )

    sel = Selection(name=name, fingerprint=fingerprint(pairs))
    sel.items = items
    db.add(sel)
    db.commit()
    db.refresh(sel)
    return sel


def get_selection(db: Session, selection_id: int) -> Selection | None:
    return db.get(Selection, selection_id)
