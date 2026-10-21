"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.database import init_db
from app.routers import documents, generations, nodes, selections


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="CT-200 Document Intelligence API",
    version=__version__,
    description=(
        "Structured, versioned document tree for the CardioTrack CT-200 manual, "
        "with version-pinned selections, LLM QA test-case generation, and "
        "staleness detection."
    ),
    lifespan=lifespan,
)

app.include_router(documents.router)
app.include_router(nodes.router)
app.include_router(selections.router)
app.include_router(generations.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "version": __version__}
