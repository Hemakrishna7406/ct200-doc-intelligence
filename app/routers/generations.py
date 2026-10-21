"""Generation + retrieval API.

* ``POST /generations``            generate test cases from a selection
* ``GET  /generations/{id}``       fetch a generation
* ``GET  /generations/{id}/staleness``  is it still valid against the latest doc?
* ``GET  /generations``            retrieve by ``selection_id`` or ``node_id``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import GenerationOut, GenerateRequest, StalenessOut
from app.services.generation import GenerationError, generate
from app.services.staleness import check_generation
from app.services.store import get_store

router = APIRouter(tags=["generations"])


@router.post("/generations", response_model=GenerationOut)
async def create_generation(req: GenerateRequest, db: Session = Depends(get_db)):
    try:
        rec = await generate(db, req.selection_id, force=req.force)
    except GenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return rec


@router.get("/generations", response_model=list[GenerationOut])
def list_generations(
    selection_id: int | None = None,
    node_id: int | None = None,
    db: Session = Depends(get_db),
):
    store = get_store()
    records = store.all()
    if selection_id is not None:
        records = [r for r in records if r.get("selection_id") == selection_id]
    if node_id is not None:
        # keep generations whose source set includes this logical node
        records = [
            r
            for r in records
            if any(s.get("node_id") == node_id for s in r.get("sources", []))
        ]
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records


@router.get("/generations/{generation_id}", response_model=GenerationOut)
def get_generation(generation_id: str):
    rec = get_store().get(generation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return rec


@router.get("/generations/{generation_id}/staleness", response_model=StalenessOut)
def generation_staleness(generation_id: str, db: Session = Depends(get_db)):
    rec = get_store().get(generation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return check_generation(db, rec)
