"""Shared pytest fixtures.

Environment is configured *before* the app package is imported, because
``app.config`` builds its Settings object (and the engine) at import time.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ct200-test-"))
os.environ["CT200_DATABASE_URL"] = f"sqlite:///{_TMP/'test.db'}"
os.environ["CT200_GENERATION_STORE_PATH"] = str(_TMP / "generations.jsonl")
os.environ["CT200_LLM_PROVIDER"] = "mock"
os.environ["CT200_OCR_ENABLED"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.store import reset_store  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"
V1 = str(DATA / "ct200_manual.pdf")
V2 = str(DATA / "ct200_manual_v2.pdf")


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
