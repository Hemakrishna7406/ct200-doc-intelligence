"""Selection API: create + fetch version-pinned selections."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NodeVersion, Selection
from app.schemas import SelectionCreate, SelectionItemOut, SelectionOut
from app.services.selection import SelectionError, create_selection

router = APIRouter(tags=["selections"])


def _to_out(db: Session, sel: Selection) -> SelectionOut:
    items = []
    for it in sel.items:
        nv = db.get(NodeVersion, it.node_version_id)
        items.append(
            SelectionItemOut(
                node_id=it.node_id,
                node_version_id=it.node_version_id,
                logical_key=nv.node.logical_key if nv else "",
                heading=nv.heading if nv else "",
                content_hash=it.content_hash,
            )
        )
    return SelectionOut(
        id=sel.id,
        name=sel.name,
        fingerprint=sel.fingerprint,
        created_at=sel.created_at,
        items=items,
    )


@router.post("/selections", response_model=SelectionOut)
def create(req: SelectionCreate, db: Session = Depends(get_db)):
    try:
        sel = create_selection(db, req.name, req.node_ids, req.version_no)
    except SelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_out(db, sel)


@router.get("/selections/{selection_id}", response_model=SelectionOut)
def get(selection_id: int, db: Session = Depends(get_db)):
    sel = db.get(Selection, selection_id)
    if sel is None:
        raise HTTPException(status_code=404, detail="selection not found")
    return _to_out(db, sel)
