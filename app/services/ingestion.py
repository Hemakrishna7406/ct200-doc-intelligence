"""Ingestion + version matching.

``ingest()`` parses a PDF and writes it as a version of a document. On the
first call every node is new (``added``). On later calls the new nodes are
matched against the document's existing *logical* nodes so that unchanged
content keeps its node id, and only genuinely edited nodes are flagged
``modified``.

Matching strategy (in priority order — see docs/APPROACH.md for failure modes):

1. **Exact numeric path** (``logical_key``). ``4.2`` in v2 is the same logical
   node as ``4.2`` in v1. This is the primary key and covers the vast majority
   of nodes.
2. **Same parent + identical normalised heading.** Catches a section that was
   renumbered but not rewritten.
3. **Unique identical normalised heading anywhere.** Catches a section that
   moved to a different parent.
4. Otherwise the node is new (``added``).

A logical node that has no counterpart in the new version is marked
``removed`` (its history is kept — nothing is deleted).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, IngestError
from app.models import Document, DocumentVersion, Node, NodeVersion
from app.parsing.extract import extract
from app.parsing.hierarchy import ParsedNode, node_content_hash, parse
from app.schemas import Anomaly, IngestResult
from app.security import resolve_document_path
from app.textutil import normalize_text


def _source_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def get_or_create_document(db: Session, name: str) -> Document:
    doc = db.scalar(select(Document).where(Document.name == name))
    if doc is None:
        doc = Document(name=name)
        db.add(doc)
        db.flush()
    return doc


def _latest_node_version(db: Session, node_id: int) -> NodeVersion | None:
    return db.scalar(
        select(NodeVersion)
        .where(NodeVersion.node_id == node_id)
        .order_by(NodeVersion.document_version_id.desc())
        .limit(1)
    )


def _latest_versions(db: Session, document_id: int) -> dict[int, NodeVersion]:
    """Latest NodeVersion per logical node, in ONE query (avoids N+1)."""
    rows = db.scalars(
        select(NodeVersion)
        .join(Node, Node.id == NodeVersion.node_id)
        .where(Node.document_id == document_id)
        .order_by(NodeVersion.node_id, NodeVersion.document_version_id)
    )
    latest: dict[int, NodeVersion] = {}
    for nv in rows:
        latest[nv.node_id] = nv  # ascending order, so the last write wins
    return latest


def _build_index(db: Session, document_id: int):
    nodes = list(db.scalars(select(Node).where(Node.document_id == document_id)))
    latest = _latest_versions(db, document_id)
    by_key: dict[str, Node] = {n.logical_key: n for n in nodes}
    by_parent_title: dict[tuple[str | None, str], Node] = {}
    by_title: dict[str, list[Node]] = {}
    for n in nodes:
        nv = latest.get(n.id)
        if nv is None:
            continue
        title = normalize_text(nv.heading).lower()
        parent_key = str(nv.parent_node_id) if nv.parent_node_id is not None else None
        by_parent_title[(parent_key, title)] = n
        by_title.setdefault(title, []).append(n)
    return by_key, by_parent_title, by_title


def _match_node(
    parsed: ParsedNode,
    parent_node: Node | None,
    by_key: dict[str, Node],
    by_parent_title: dict[tuple[str, str], Node],
    by_title: dict[str, list[Node]],
) -> Node | None:
    if parsed.logical_key in by_key:
        return by_key[parsed.logical_key]
    title = normalize_text(parsed.heading).lower()
    if parent_node is not None:
        hit = by_parent_title.get((str(parent_node.id), title))
        if hit is not None:
            return hit
    cands = by_title.get(title, [])
    if len(cands) == 1:
        return cands[0]
    return None


def ingest(
    db: Session,
    path: str,
    document_name: str,
    version_no: int | None = None,
    notes: str | None = None,
) -> IngestResult:
    if not document_name or not document_name.strip():
        raise IngestError("document_name must be a non-empty string")
    if version_no is not None and version_no < 1:
        raise IngestError("version_no must be >= 1")

    # confine reads to the configured document root (see app/security.py)
    resolved = resolve_document_path(path)

    doc = get_or_create_document(db, document_name)

    existing_versions = list(
        db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
        )
    )
    if version_no is None:
        version_no = max((v.version_no for v in existing_versions), default=0) + 1
    elif any(v.version_no == version_no for v in existing_versions):
        raise ConflictError(
            f"document {document_name!r} already has a version {version_no}"
        )

    try:
        extraction = extract(str(resolved))
        parsed = parse(extraction)
    except Exception as exc:  # pymupdf raises a variety of errors on bad input
        raise IngestError(f"could not parse PDF {resolved.name!r}: {exc}") from exc

    if not parsed.nodes:
        raise IngestError(f"no content extracted from {resolved.name!r}")

    for v in existing_versions:
        v.is_latest = False

    dv = DocumentVersion(
        document_id=doc.id,
        version_no=version_no,
        source_filename=resolved.name,
        source_hash=_source_hash(str(resolved)),
        page_count=extraction.page_count,
        is_latest=True,
        notes=notes,
    )
    db.add(dv)
    db.flush()

    by_key, by_parent_title, by_title = _build_index(db, doc.id)

    # process parents before children so parent ids are always known
    ordered = sorted(parsed.nodes, key=lambda n: (n.level, n.sort_key))

    key_to_node: dict[str, Node] = {}
    counts = {"added": 0, "modified": 0, "unchanged": 0}
    matched_node_ids: set[int] = set()
    anomalies: list[Anomaly] = []

    for pn in ordered:
        parent_node = key_to_node.get(pn.parent_key) if pn.parent_key else None

        node = _match_node(pn, parent_node, by_key, by_parent_title, by_title)
        if node is None:
            node = Node(
                document_id=doc.id,
                logical_key=pn.logical_key,
                kind=pn.kind,
                first_seen_version_id=dv.id,
            )
            db.add(node)
            db.flush()
            status = "added"
        else:
            matched_node_ids.add(node.id)
            prev = _latest_node_version(db, node.id)
            new_hash = node_content_hash(pn)
            status = (
                "unchanged" if prev is not None and prev.content_hash == new_hash
                else "modified"
            )
            # a node that had been removed and comes back is simply present again
            node.removed_at_version_id = None

        new_hash = node_content_hash(pn)
        nv = NodeVersion(
            node_id=node.id,
            document_version_id=dv.id,
            parent_node_id=parent_node.id if parent_node else None,
            level=pn.level,
            number=pn.number,
            heading=pn.heading,
            body_text=pn.body_text,
            content_hash=new_hash,
            source_order=pn.source_order,
            kind=pn.kind,
            table_json=pn.table,
            anomalies=pn.anomalies or None,
            change_status=status,
        )
        db.add(nv)
        db.flush()
        if parent_node is not None:
            nv.parent_node_version_id = db.scalar(
                select(NodeVersion.id).where(
                    NodeVersion.node_id == parent_node.id,
                    NodeVersion.document_version_id == dv.id,
                )
            )
        key_to_node[pn.logical_key] = node
        counts[status] += 1

        for a in pn.anomalies:
            anomalies.append(Anomaly(**a))

    # mark nodes absent from this version as removed
    removed = 0
    for node in db.scalars(select(Node).where(Node.document_id == doc.id)):
        if node.id not in matched_node_ids and node.logical_key not in {
            p.logical_key for p in parsed.nodes
        }:
            # only consider nodes that existed *before* this version
            prev = _latest_node_version(db, node.id)
            if prev is not None and prev.document_version_id < dv.id:
                node.removed_at_version_id = dv.id
                removed += 1

    db.commit()

    return IngestResult(
        document_id=doc.id,
        document_name=doc.name,
        version_id=dv.id,
        version_no=dv.version_no,
        node_count=len(parsed.nodes),
        added=counts["added"],
        modified=counts["modified"],
        unchanged=counts["unchanged"],
        removed=removed,
        anomalies=anomalies,
    )
