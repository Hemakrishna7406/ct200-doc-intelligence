"""Removed-node detection: a section deleted in a later version must be marked
removed (not deleted), report as ``removed`` in the change endpoint, and drive a
generation's staleness to ``missing``."""

from __future__ import annotations

from tests.conftest import DOCROOT
from tests.pdfgen import make_pdf


def _synth(name: str, blocks):
    return make_pdf(DOCROOT / name, blocks)


def _node_id(client, doc_id, q, key, version=None):
    params = {"q": q}
    if version is not None:
        params["version"] = version
    hits = client.get(f"/documents/{doc_id}/search", params=params).json()
    return next(h for h in hits if h["logical_key"] == key)["node_id"]


def test_removed_section_is_detected_and_queryable(client):
    v1 = _synth("synth_v1.pdf", [
        ("1. Alpha", 1), ("Alpha body.", 0),
        ("1.1 Beta", 2), ("Beta body.", 0),
        ("2. Gamma", 1), ("Gamma body.", 0),
    ])
    v2 = _synth("synth_v2.pdf", [
        ("1. Alpha", 1), ("Alpha body.", 0),
        ("1.1 Beta", 2), ("Beta body.", 0),
        # section 2 removed entirely
    ])

    doc_id = client.post(
        "/documents/ingest", json={"path": v1, "document_name": "Synth"}
    ).json()["document_id"]

    res = client.post(
        "/documents/ingest", json={"path": v2, "document_name": "Synth"}
    ).json()
    assert res["removed"] == 1

    gamma = _node_id(client, doc_id, "Gamma", "2", version=1)
    ch = client.get(f"/nodes/{gamma}/changes", params={"from": 1, "to": 2}).json()
    assert ch["status"] == "removed"

    # section 2 is gone from the latest top-level listing
    top = client.get(f"/documents/{doc_id}/sections").json()
    assert "2" not in [s["logical_key"] for s in top]
    # but it is still visible in v1
    top1 = client.get(f"/documents/{doc_id}/sections", params={"version": 1}).json()
    assert "2" in [s["logical_key"] for s in top1]


def test_generation_on_removed_node_becomes_missing(client):
    v1 = _synth("synth2_v1.pdf", [
        ("1. Alpha", 1), ("Alpha body.", 0),
        ("2. Gamma", 1), ("Gamma body.", 0),
    ])
    v2 = _synth("synth2_v2.pdf", [("1. Alpha", 1), ("Alpha body.", 0)])

    doc_id = client.post(
        "/documents/ingest", json={"path": v1, "document_name": "Synth2"}
    ).json()["document_id"]
    gamma = _node_id(client, doc_id, "Gamma", "2")

    sel = client.post("/selections", json={"name": "g", "node_ids": [gamma]}).json()
    gen = client.post("/generations", json={"selection_id": sel["id"]}).json()
    assert gen["status"] == "completed"

    client.post("/documents/ingest", json={"path": v2, "document_name": "Synth2"})
    st = client.get(f"/generations/{gen['generation_id']}/staleness").json()
    assert st["overall"] == "missing"
    assert st["sources"][0]["status"] == "missing"
