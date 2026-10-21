"""Versioning tests: re-ingesting v2 must preserve identity for unchanged nodes
and flag exactly the nodes that changed."""

from __future__ import annotations

from tests.conftest import V2


def _node_id(client, doc_id, key):
    hits = client.get(f"/documents/{doc_id}/search", params={"q": key}).json()
    return {h["logical_key"]: h["node_id"] for h in hits}


def test_v2_reingest_summary(ingested):
    client, doc_id = ingested
    r = client.post(
        "/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"}
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["version_no"] == 2
    # exactly one new section (5.3 Data Export)
    assert s["added"] == 1
    # 2.1.1.1, 3.2, 4.2's table, 4.3 changed
    assert s["modified"] == 4
    assert s["removed"] == 0
    assert s["unchanged"] >= 20


def test_unchanged_node_keeps_its_id_across_versions(ingested):
    client, doc_id = ingested
    before = _node_id(client, doc_id, "Intended Use")["1.1"]
    client.post("/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"})
    after = _node_id(client, doc_id, "Intended Use")["1.1"]
    assert before == after, "an unchanged section must keep the same logical node id"


def test_new_section_appears_only_in_v2(ingested):
    client, doc_id = ingested
    assert client.get(
        f"/documents/{doc_id}/search", params={"q": "Data Export", "version": 1}
    ).json() == []
    client.post("/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"})
    hits = client.get(
        f"/documents/{doc_id}/search", params={"q": "Data Export", "version": 2}
    ).json()
    assert [h["logical_key"] for h in hits] == ["5.3"]
    assert hits[0]["change_status"] == "added"


def test_changed_sections_are_flagged(ingested):
    client, doc_id = ingested
    client.post("/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"})
    # 3.2 changed its inflation increment 40 -> 30 mmHg
    hits = client.get(
        f"/documents/{doc_id}/search", params={"q": "Cuff Inflation"}
    ).json()
    assert hits[0]["change_status"] == "modified"
    # a container whose table changed reports modified too
    ec = client.get(f"/documents/{doc_id}/search", params={"q": "Error Codes"}).json()
    n42 = [h for h in ec if h["logical_key"] == "4.2"][0]["node_id"]
    ch = client.get(f"/nodes/{n42}/changes", params={"from": 1, "to": 2}).json()
    assert ch["status"] == "modified"


def test_version_pinned_selection_resolves_to_v1_text_after_v2(ingested):
    client, doc_id = ingested
    n32 = client.get(
        f"/documents/{doc_id}/search", params={"q": "Cuff Inflation"}
    ).json()[0]["node_id"]
    sel = client.post(
        "/selections",
        json={"name": "inflation", "node_ids": [n32], "version_no": 1},
    ).json()
    # now re-ingest
    client.post("/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"})
    # the selection still points at the v1 node version
    sel2 = client.get(f"/selections/{sel['id']}").json()
    v1_item = sel2["items"][0]
    node_v1 = client.get(
        f"/nodes/{v1_item['node_id']}", params={"version": 1}
    ).json()
    assert "40 mmHg" in node_v1["body_text"]
    assert node_v1["content_hash"] == v1_item["content_hash"]
