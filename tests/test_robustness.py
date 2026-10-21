"""Robustness: bad input must produce clean 4xx responses, never a 500."""

from __future__ import annotations

from tests.conftest import V1


def test_duplicate_version_is_a_conflict(ingested):
    client, _ = ingested
    r = client.post(
        "/documents/ingest",
        json={"path": V1, "document_name": "CT-200 Manual", "version_no": 1},
    )
    assert r.status_code == 409
    assert "already has a version" in r.json()["detail"]


def test_missing_file_is_400(client):
    r = client.post(
        "/documents/ingest",
        json={"path": "does_not_exist.pdf", "document_name": "x"},
    )
    assert r.status_code == 400


def test_empty_document_name_is_400(client):
    r = client.post(
        "/documents/ingest", json={"path": V1, "document_name": "   "}
    )
    assert r.status_code == 400


def test_invalid_version_number_is_400(client):
    r = client.post(
        "/documents/ingest",
        json={"path": V1, "document_name": "x", "version_no": 0},
    )
    assert r.status_code == 400


def test_malformed_body_is_422(client):
    r = client.post("/documents/ingest", json={"document_name": "x"})
    assert r.status_code == 422


def test_unknown_document_versions_is_404(client):
    assert client.get("/documents/999/versions").status_code == 404


def test_node_not_in_that_version_is_404(ingested):
    client, doc_id = ingested
    node_id = client.get(
        f"/documents/{doc_id}/search", params={"q": "Intended Use"}
    ).json()[0]["node_id"]
    assert client.get(f"/nodes/{node_id}", params={"version": 99}).status_code == 404


def test_generation_for_missing_selection_is_400(client):
    r = client.post("/generations", json={"selection_id": 12345})
    assert r.status_code == 400
