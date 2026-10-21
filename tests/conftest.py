"""Shared pytest fixtures.

Environment is configured *before* the app package is imported, because
``app.config`` builds its Settings object (and the engine) at import time.

Tests run against an **isolated document root**: the two sample PDFs are copied
into a temp directory which becomes ``CT200_DOCUMENT_ROOT``, so tests can create
synthetic PDFs without touching the repo's ``data/`` and the path-confinement
logic is exercised for real.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ct200-test-"))
_DOCROOT = _TMP / "docs"
_DOCROOT.mkdir(parents=True, exist_ok=True)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DATA = _REPO_ROOT / "data"
for _pdf in ("ct200_manual.pdf", "ct200_manual_v2.pdf"):
    shutil.copy(_SRC_DATA / _pdf, _DOCROOT / _pdf)

os.environ["CT200_DATABASE_URL"] = f"sqlite:///{_TMP/'test.db'}"
os.environ["CT200_GENERATION_STORE_PATH"] = str(_TMP / "generations.jsonl")
os.environ["CT200_LLM_PROVIDER"] = "mock"
os.environ["CT200_OCR_ENABLED"] = "true"
os.environ["CT200_DOCUMENT_ROOT"] = str(_DOCROOT)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.store import reset_store  # noqa: E402

REPO_ROOT = _REPO_ROOT
DOCROOT = _DOCROOT
V1 = str(_DOCROOT / "ct200_manual.pdf")
V2 = str(_DOCROOT / "ct200_manual_v2.pdf")


@pytest.fixture()
def client():
    """A clean database + empty generation store for every test."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_store()
    Path(os.environ["CT200_GENERATION_STORE_PATH"]).write_text("")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def ingested(client):
    """A client with v1 ingested; returns (client, document_id)."""
    r = client.post(
        "/documents/ingest",
        json={"path": V1, "document_name": "CT-200 Manual"},
    )
    assert r.status_code == 200, r.text
    return client, r.json()["document_id"]
