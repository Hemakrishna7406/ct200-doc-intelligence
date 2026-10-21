"""Read-side queries backing the Browse / Retrieval APIs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentVersion, Node, NodeVersion
from app.services.diffing import diff_summary, line_diff
from app.services.tree import subtree_node_versions
from app.textutil import normalize_text


def _effective_text(db: Session, node_id: int, version_id: int) -> str:
    """Own text + all descendants' text — what a container really contains."""
    from app.services.generation import node_version_text

    return "\n".join(
        node_version_text(nv)
        for nv in subtree_node_versions(db, node_id, version_id)
    )


def resolve_version(
    db: Session, document_id: int, version_no: int | None
) -> DocumentVersion | None:
    q = select(DocumentVersion).where(DocumentVersion.document_id == document_id)
    if version_no is not None:
        q = q.where(DocumentVersion.version_no == version_no)
    else:
        q = q.order_by(DocumentVersion.version_no.desc())
    return db.scalar(q.limit(1))


def _nv(db: Session, node_id: int, version_id: int) -> NodeVersion | None:
    return db.scalar(
        select(NodeVersion).where(
            NodeVersion.node_id == node_id,
            NodeVersion.document_version_id == version_id,
        )
    )


def _has_children(db: Session, node_id: int, version_id: int) -> bool:
    return (
        db.scalar(
            select(NodeVersion.id)
            .where(
                NodeVersion.parent_node_id == node_id,
                NodeVersion.document_version_id == version_id,
            )
            .limit(1)
        )
        is not None
    )


def _node_out(db: Session, nv: NodeVersion, version_id: int) -> dict:
    return {
        "node_id": nv.node_id,
        "node_version_id": nv.id,
        "logical_key": nv.node.logical_key,
        "number": nv.number,
        "heading": nv.heading,
        "level": nv.level,
        "kind": nv.kind,
        "content_hash": nv.content_hash,
        "change_status": nv.change_status,
        "has_children": _has_children(db, nv.node_id, version_id),
        "anomalies": [a.get("code", str(a)) for a in (nv.anomalies or [])],
    }


def list_top_sections(db: Session, document_id: int, version_no: int | None) -> list[dict]:
    dv = resolve_version(db, document_id, version_no)
    if dv is None:
        return []
    root = db.scalar(
        select(NodeVersion).where(
            NodeVersion.document_version_id == dv.id, NodeVersion.kind == "document"
        )
    )
    parent_id = root.node_id if root else None
    q = select(NodeVersion).where(NodeVersion.document_version_id == dv.id)
    if parent_id is not None:
        q = q.where(NodeVersion.parent_node_id == parent_id)
    else:
        q = q.where(NodeVersion.level == 1)
    rows = list(db.scalars(q))
    rows.sort(key=lambda nv: _sort_key(nv))
    return [_node_out(db, nv, dv.id) for nv in rows]


def _sort_key(nv: NodeVersion):
    if nv.number:
        return (0, tuple(int(x) for x in nv.number.split(".")))
    return (1, (nv.source_order,))


def get_node_detail(db: Session, node_id: int, version_no: int | None) -> dict | None:
    node = db.get(Node, node_id)
    if node is None:
        return None
    dv = resolve_version(db, node.document_id, version_no)
    if dv is None:
        return None
    nv = _nv(db, node_id, dv.id)
    if nv is None:
        return None
    children = list(
        db.scalars(
            select(NodeVersion).where(
                NodeVersion.parent_node_id == node_id,
                NodeVersion.document_version_id == dv.id,
            )
        )
    )
    children.sort(key=_sort_key)
    out = _node_out(db, nv, dv.id)
    out.update(
        {
            "body_text": nv.body_text,
            "table": nv.table_json,
            "parent_node_id": nv.parent_node_id,
            "children": [_node_out(db, c, dv.id) for c in children],
            "version_no": dv.version_no,
        }
    )
    return out


def search_nodes(
    db: Session, document_id: int, q: str, version_no: int | None
) -> list[dict]:
    dv = resolve_version(db, document_id, version_no)
    if dv is None:
        return []
    needle = normalize_text(q).lower()
    rows = list(
        db.scalars(select(NodeVersion).where(NodeVersion.document_version_id == dv.id))
    )
    hits = []
    for nv in rows:
        hay = normalize_text(f"{nv.heading}\n{nv.body_text}").lower()
        if needle in hay:
            hits.append(_node_out(db, nv, dv.id))
    hits.sort(key=lambda d: (d["level"], d["logical_key"]))
    return hits


def node_changes(
    db: Session, node_id: int, from_version: int, to_version: int
) -> dict | None:
    node = db.get(Node, node_id)
    if node is None:
        return None
    dv_from = resolve_version(db, node.document_id, from_version)
    dv_to = resolve_version(db, node.document_id, to_version)
    if dv_to is None:
        return None
    nv_from = _nv(db, node_id, dv_from.id) if dv_from else None
    nv_to = _nv(db, node_id, dv_to.id)

    if nv_from is None and nv_to is None:
        return None
    if nv_from is None:
        status = "added"
    elif nv_to is None:
        status = "removed"
    else:
        # compare the *subtree* text so a container whose child table changed is
        # reported as modified, not unchanged
        old = _effective_text(db, node_id, dv_from.id)
        new = _effective_text(db, node_id, dv_to.id)
        status = "unchanged" if normalize_text(old) == normalize_text(new) else "modified"

    changed_lines: list[str] = []
    summary = None
    if status == "modified":
        old = _effective_text(db, node_id, dv_from.id)
        new = _effective_text(db, node_id, dv_to.id)
        changed_lines = line_diff(old, new)
        summary = diff_summary(old, new)
    elif status == "added":
        summary = "node introduced in this version"
    elif status == "removed":
        summary = "node absent from this version"

    heading = (nv_to or nv_from).heading
    return {
        "node_id": node_id,
        "logical_key": node.logical_key,
        "heading": heading,
        "status": status,
        "from_version": dv_from.version_no if dv_from else None,
        "to_version": dv_to.version_no,
        "diff_summary": summary,
        "changed_lines": changed_lines,
    }
