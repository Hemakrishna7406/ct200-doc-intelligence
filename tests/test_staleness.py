"""Staleness + generation tests."""

from __future__ import annotations

from tests.conftest import V2


def _nid(client, doc_id, q, key):
    hits = client.get(f"/documents/{doc_id}/search", params={"q": q}).json()
    return next(h for h in hits if h["logical_key"] == key)["node_id"]


def _make_generation(client, doc_id, node_ids):
    sel = client.post(
        "/selections", json={"name": "sel", "node_ids": node_ids}
    ).json()
    return client.post("/generations", json={"selection_id": sel["id"]}).json()


def test_generation_is_current_before_reingest(ingested):
    client, doc_id = ingested
    n = _nid(client, doc_id, "Cuff Inflation", "3.2")
    g = _make_generation(client, doc_id, [n])
    assert g["status"] == "completed"
    assert 3 <= len(g["test_cases"]) <= 5
    st = client.get(f"/generations/{g['generation_id']}/staleness").json()
    assert st["overall"] == "current"


def test_generation_goes_stale_after_reingest(ingested):
    client, doc_id = ingested
    n32 = _nid(client, doc_id, "Cuff Inflation", "3.2")
    n11 = _nid(client, doc_id, "Intended Use", "1.1")
    g = _make_generation(client, doc_id, [n32, n11])

    client.post("/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"})
    st = client.get(f"/generations/{g['generation_id']}/staleness").json()

    assert st["overall"] == "partially_stale"
    by_key = {s["logical_key"]: s for s in st["sources"]}
    assert by_key["3.2"]["status"] == "stale"
    assert by_key["3.2"]["magnitude"] == "major"  # numeric threshold changed
    assert by_key["1.1"]["status"] == "current"  # untouched section


def test_container_generation_goes_stale_when_child_table_changes(ingested):
    """Selecting 4.2 must pull in its error-code table and go stale when the
    table changes — even though 4.2's own heading text never changes."""
    client, doc_id = ingested
    n42 = _nid(client, doc_id, "Error Codes", "4.2")
    g = _make_generation(client, doc_id, [n42])
    roles = {s["logical_key"]: s["role"] for s in g["sources"]}
    assert any(r == "descendant" for r in roles.values())

    client.post("/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"})
    st = client.get(f"/generations/{g['generation_id']}/staleness").json()
    # the section heading is unchanged but its table changed -> not current
    assert st["overall"] != "current"
    table = next(s for s in st["sources"] if s["role"] == "descendant")
    assert table["status"] == "stale"


def test_retrieval_by_selection_and_by_node(ingested):
    client, doc_id = ingested
    n = _nid(client, doc_id, "Cuff Inflation", "3.2")
    g = _make_generation(client, doc_id, [n])
    by_sel = client.get(
        "/generations", params={"selection_id": g["selection_id"]}
    ).json()
    by_node = client.get("/generations", params={"node_id": n}).json()
    assert g["generation_id"] in {x["generation_id"] for x in by_sel}
    assert g["generation_id"] in {x["generation_id"] for x in by_node}


def test_generation_is_idempotent(ingested):
    client, doc_id = ingested
    n = _nid(client, doc_id, "Cuff Inflation", "3.2")
    sel = client.post("/selections", json={"name": "s", "node_ids": [n]}).json()
    g1 = client.post("/generations", json={"selection_id": sel["id"]}).json()
    g2 = client.post("/generations", json={"selection_id": sel["id"]}).json()
    assert g2["idempotent_hit"] is True
    assert g2["generation_id"] == g1["generation_id"]
    # force=True produces a new generation
    g3 = client.post(
        "/generations", json={"selection_id": sel["id"], "force": True}
    ).json()
    assert g3["idempotent_hit"] is False
    assert g3["generation_id"] != g1["generation_id"]
