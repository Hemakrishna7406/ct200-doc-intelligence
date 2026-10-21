"""Browse API: top-level sections, node detail, search, cross-version changes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ChangeOut, NodeDetail, NodeOut
from app.services import browse

router = APIRouter(tags=["browse"])


@router.get("/documents/{document_id}/sections", response_model=list[NodeOut])
def top_level_sections(
    document_id: int,
    version: int | None = Query(None, description="Version number; default = latest"),
    db: Session = Depends(get_db),
):
    return browse.list_top_sections(db, document_id, version)


@router.get("/documents/{document_id}/search", response_model=list[NodeOut])
def search(
    document_id: int,
    q: str = Query(..., min_length=1),
    version: int | None = None,
    db: Session = Depends(get_db),
):
    return browse.search_nodes(db, document_id, q, version)


@router.get("/nodes/{node_id}", response_model=NodeDetail)
def node_detail(
    node_id: int,
    version: int | None = None,
    db: Session = Depends(get_db),
):
    detail = browse.get_node_detail(db, node_id, version)
    if detail is None:
        raise HTTPException(status_code=404, detail="node not found in that version")
    return detail


@router.get("/nodes/{node_id}/changes", response_model=ChangeOut)
def node_changes(
    node_id: int,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
    db: Session = Depends(get_db),
):
    change = browse.node_changes(db, node_id, from_version, to_version)
    if change is None:
        raise HTTPException(status_code=404, detail="node not found")
    return change
