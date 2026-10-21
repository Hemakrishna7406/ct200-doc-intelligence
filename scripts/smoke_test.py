#!/usr/bin/env python3
"""No-server smoke test: drives the API in-process with TestClient.

    python scripts/smoke_test.py

Exits non-zero on any failed assertion. Useful in CI where you do not want to
bind a port.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = Path(tempfile.mkdtemp(prefix="ct200-smoke-"))
os.environ["CT200_DATABASE_URL"] = f"sqlite:///{_tmp/'smoke.db'}"
os.environ["CT200_GENERATION_STORE_PATH"] = str(_tmp / "generations.jsonl")
os.environ["CT200_LLM_PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> int:
    with TestClient(app) as c:
        doc_id = c.post(
            "/documents/ingest",
            json={"path": "data/ct200_manual.pdf", "document_name": "CT-200 Manual"},
        ).json()["document_id"]

        hits = c.get(f"/documents/{doc_id}/search", params={"q": "Error Codes"}).json()
        n42 = [h for h in hits if h["logical_key"] == "4.2"][0]["node_id"]

        sel = c.post("/selections", json={"name": "s", "node_ids": [n42]}).json()
        gen = c.post("/generations", json={"selection_id": sel["id"]}).json()
        assert gen["status"] == "completed", gen

        before = c.get(f"/generations/{gen['generation_id']}/staleness").json()
        assert before["overall"] == "current", before

        c.post(
            "/documents/ingest",
            json={"path": "data/ct200_manual_v2.pdf", "document_name": "CT-200 Manual"},
        )
        after = c.get(f"/generations/{gen['generation_id']}/staleness").json()
        assert after["overall"] != "current", after

        print("smoke OK: generation went", before["overall"], "->", after["overall"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
