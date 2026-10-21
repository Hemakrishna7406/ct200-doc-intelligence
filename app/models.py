"""SQLAlchemy ORM models for the structured store.

Design notes (see docs/APPROACH.md for the full rationale):

* ``Node`` is the *logical* node — it is stable across document versions. A
  node's identity is its ``logical_key`` (its canonical numeric path, e.g.
  ``"4.2"``) scoped to a document.
* ``NodeVersion`` is the *snapshot* of a node in one document version. All the
  content that can change (heading text, body, tables, parent, hash) lives
  here. This is what makes version-pinned selections and staleness checks
  possible.
* ``content_hash`` is a hash of *normalised* text, so cosmetic differences
  (whitespace, unicode ligatures, page-break position) never register as a
  change.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    nodes: Mapped[list[Node]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    source_filename: Mapped[str] = mapped_column(String(255))
    source_hash: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[Document] = relationship(back_populates="versions")
    node_versions: Mapped[list[NodeVersion]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class Node(Base):
    """A logical document node, stable across versions."""

    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("document_id", "logical_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    # canonical numeric path ("4.2") or synthetic key ("title", "4.2#table1")
    logical_key: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="section")  # document|section|table
    first_seen_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    # set when the node is absent from the latest version (removed, not deleted)
    removed_at_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped[Document] = relationship(back_populates="nodes")
    versions: Mapped[list[NodeVersion]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        foreign_keys="NodeVersion.node_id",
    )


class NodeVersion(Base):
    """A node's content in one document version."""

    __tablename__ = "node_versions"
    __table_args__ = (UniqueConstraint("node_id", "document_version_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), index=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id"), index=True
    )

    # logical + version-local parent links
    parent_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id"), nullable=True, index=True
    )
    parent_node_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("node_versions.id"), nullable=True
    )

    level: Mapped[int] = mapped_column(Integer, default=0)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heading: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_order: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20), default="section")

    table_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    anomalies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # unchanged | modified | added | removed  (relative to the previous version)
    change_status: Mapped[str] = mapped_column(String(20), default="unchanged")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    node: Mapped[Node] = relationship(
        back_populates="versions", foreign_keys=[node_id]
    )
    document_version: Mapped[DocumentVersion] = relationship(back_populates="node_versions")


class Selection(Base):
    """A named, version-pinned set of node versions."""

    __tablename__ = "selections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # sha256 over the sorted (node_id, node_version_id) pairs — used for
    # idempotency and as a stable handle for a selection's content.
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    items: Mapped[list[SelectionItem]] = relationship(
        back_populates="selection", cascade="all, delete-orphan"
    )


class SelectionItem(Base):
    __tablename__ = "selection_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))
    node_version_id: Mapped[int] = mapped_column(ForeignKey("node_versions.id"))
    # the exact content the selection was pinned against
    content_hash: Mapped[str] = mapped_column(String(64))

    selection: Mapped[Selection] = relationship(back_populates="items")
