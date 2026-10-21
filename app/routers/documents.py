"""Document ingestion + version listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, DocumentVersion
from app.schemas import DocumentOut, DocumentVersionOut, IngestRequest, IngestResult
from app.services.ingestion import ingest

router = APIRouter(tags=["documents"])


@router.post("/documents/ingest", response_model=IngestResult)
def ingest_document(req: IngestRequest, db: Session = Depends(get_db)) -> IngestResult:
    # validation / path-safety / parse failures raise AppError subclasses,
    # which the global handlers turn into clean 4xx responses
    return ingest(
        db,
        path=req.path,
        document_name=req.document_name,
        version_no=req.version_no,
        notes=req.notes,
    )


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentOut]:
    docs = list(db.scalars(select(Document)))
    out = []
    for d in docs:
        versions = list(
            db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == d.id)
                .order_by(DocumentVersion.version_no)
            )
        )
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "versions": [v.version_no for v in versions],
                "latest_version": max((v.version_no for v in versions), default=None),
            }
        )
    return out


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
def list_versions(document_id: int, db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no)
        )
    )
    if not rows:
        raise HTTPException(status_code=404, detail="document not found")
    return rows
