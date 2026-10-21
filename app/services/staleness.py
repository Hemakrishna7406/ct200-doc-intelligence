"""Staleness / impact detection.

A generation records the ``content_hash`` (and the full text) of every node
version it was built from. At retrieval time we re-resolve each of those nodes
to its **current** version and compare hashes:

* equal  -> ``current``  (the test cases still reflect the source)
* differ -> ``stale``    (the source text changed under the generation)
* node gone in the latest version -> ``missing``

Because the comparison is on the *logical node*, a re-ingest that merely moves
content across a page break does not flag anything — only a real edit does.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Node, NodeVersion
from app.services.diffing import change_magnitude, diff_summary
from app.services.tree import node_version_text


def _current_node_version(db: Session, node_id: int) -> NodeVersion | None:
    return db.scalar(
        select(NodeVersion)
        .join(Node, Node.id == NodeVersion.node_id)
        .where(NodeVersion.node_id == node_id, Node.removed_at_version_id.is_(None))
        .order_by(NodeVersion.document_version_id.desc())
        .limit(1)
    )


def check_generation(db: Session, record: dict) -> dict:
    sources = []
    statuses = set()
    for src in record.get("sources", []):
        node_id = src["node_id"]
        generated_hash = src["content_hash"]
        nv = _current_node_version(db, node_id)
        if nv is None:
            statuses.add("missing")
            sources.append(
                {
                    "node_id": node_id,
                    "logical_key": src["logical_key"],
                    "heading": src["heading"],
                    "role": src.get("role", "selected"),
                    "status": "missing",
                    "magnitude": "none",
                    "generated_from_hash": generated_hash,
                    "current_hash": None,
                    "diff_summary": "node no longer present in the latest version",
                }
            )
            continue
        if nv.content_hash == generated_hash:
            statuses.add("current")
            sources.append(
                {
                    "node_id": node_id,
                    "logical_key": src["logical_key"],
                    "heading": nv.heading,
                    "role": src.get("role", "selected"),
                    "status": "current",
                    "magnitude": "none",
                    "generated_from_hash": generated_hash,
                    "current_hash": nv.content_hash,
                    "diff_summary": "no change",
                }
            )
        else:
            statuses.add("stale")
            old_text = src.get("text", "")
            new_text = node_version_text(nv)
            sources.append(
                {
                    "node_id": node_id,
                    "logical_key": src["logical_key"],
                    "heading": nv.heading,
                    "role": src.get("role", "selected"),
                    "status": "stale",
                    "magnitude": change_magnitude(old_text, new_text),
                    "generated_from_hash": generated_hash,
                    "current_hash": nv.content_hash,
                    "diff_summary": diff_summary(old_text, new_text),
                }
            )

    if not statuses or statuses == {"current"}:
        overall = "current"
    elif statuses == {"stale"}:
        overall = "stale"
    elif statuses == {"missing"}:
        overall = "missing"
    else:
        overall = "partially_stale"

    return {
        "generation_id": record["generation_id"],
        "overall": overall,
        "checked_at": datetime.now(timezone.utc),
        "sources": sources,
    }
