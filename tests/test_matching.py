"""Version-matching rules 2 and 3: a section that is renumbered or moved must
keep its logical identity (so its history and staleness links survive)."""

from __future__ import annotations

from tests.conftest import DOCROOT
from tests.pdfgen import make_pdf


def _synth(name, blocks):
    return make_pdf(DOCROOT / name, blocks)


def _nid(client, doc_id, q, key):
    hits = client.get(f"/documents/{doc_id}/search", params={"q": q}).json()
    return next(h for h in hits if h["logical_key"] == key)["node_id"]


def test_renumbered_section_keeps_its_id(client):
    v1 = _synth("ren_v1.pdf", [("1. Alpha", 1), ("a", 0), ("1.1 Beta", 2), ("b", 0)])
    v2 = _synth("ren_v2.pdf", [("1. Alpha", 1), ("a", 0), ("1.2 Beta", 2), ("b", 0)])

    doc_id = client.post(
        "/documents/ingest", json={"path": v1, "document_name": "Ren"}
    ).json()["document_id"]
    before = _nid(client, doc_id, "Beta", "1.1")

    client.post("/documents/ingest", json={"path": v2, "document_name": "Ren"})
    after = _nid(client, doc_id, "Beta", "1.2")

    assert before == after, "a renumbered section should keep its logical node id"


def test_moved_section_keeps_its_id(client):
    v1 = _synth("mv_v1.pdf", [("1. Alpha", 1), ("a", 0), ("1.1 Beta", 2), ("b", 0)])
    v2 = _synth("mv_v2.pdf", [("2. Alpha", 1), ("a", 0), ("2.1 Beta", 2), ("b", 0)])

    doc_id = client.post(
        "/documents/ingest", json={"path": v1, "document_name": "Mv"}
    ).json()["document_id"]
    before = _nid(client, doc_id, "Beta", "1.1")

    client.post("/documents/ingest", json={"path": v2, "document_name": "Mv"})
    after = _nid(client, doc_id, "Beta", "2.1")

    assert before == after, "a section moved to a new parent should keep its id"
