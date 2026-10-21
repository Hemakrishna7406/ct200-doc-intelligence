"""End-to-end API flow: ingest v1 -> browse -> select -> generate ->
re-ingest v2 -> staleness -> retrieval."""

from __future__ import annotations

from tests.conftest import V2


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_full_versioning_and_staleness_flow(ingested):
    client, doc_id = ingested

    # 1. browse top-level sections
    sections = client.get(f"/documents/{doc_id}/sections").json()
    keys = [s["logical_key"] for s in sections]
    assert keys == ["1", "2", "3", "4", "5", "6", "7", "8"]

    # 2. node detail carries children + hash + table
    n42 = [h for h in client.get(
        f"/documents/{doc_id}/search", params={"q": "Error Codes"}
    ).json() if h["logical_key"] == "4.2"][0]["node_id"]
    detail = client.get(f"/nodes/{n42}").json()
    assert detail["children"][0]["kind"] == "table"
    assert detail["content_hash"]

    # 3. selection + generation
    n32 = client.get(
        f"/documents/{doc_id}/search", params={"q": "Cuff Inflation"}
    ).json()[0]["node_id"]
    sel = client.post(
        "/selections", json={"name": "review", "node_ids": [n32, n42]}
    ).json()
    gen = client.post("/generations", json={"selection_id": sel["id"]}).json()
    assert gen["status"] == "completed"
    assert all(tc["requirement_ref"] for tc in gen["test_cases"])

    # 4. current before re-ingest
    assert client.get(
        f"/generations/{gen['generation_id']}/staleness"
    ).json()["overall"] == "current"

    # 5. re-ingest v2
    v2 = client.post(
        "/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"}
    ).json()
    assert v2["version_no"] == 2

    # 6. staleness now flags the changed sources
    st = client.get(f"/generations/{gen['generation_id']}/staleness").json()
    assert st["overall"] in {"stale", "partially_stale"}

    # 7. retrieval by selection and node
    assert client.get("/generations", params={"selection_id": sel["id"]}).json()
    assert client.get("/generations", params={"node_id": n32}).json()

    # 8. cross-version change endpoint
    ch = client.get(f"/nodes/{n32}/changes", params={"from": 1, "to": 2}).json()
    assert ch["status"] == "modified"
    assert ch["changed_lines"]


def test_selection_rejects_unknown_node(client, ingested):
    _, doc_id = ingested
    r = client.post("/selections", json={"name": "bad", "node_ids": [999999]})
    assert r.status_code == 400
