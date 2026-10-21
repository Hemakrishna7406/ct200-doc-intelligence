#!/usr/bin/env python3
"""End-to-end demo against a *running* server.

Start the API first:

    uvicorn app.main:app --reload

then:

    python scripts/e2e_demo.py

It walks the whole flow: ingest v1 -> browse -> search -> select -> generate ->
re-ingest v2 -> check staleness -> retrieve. Prints a readable trace.
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8000"
V1 = "data/ct200_manual.pdf"
V2 = "data/ct200_manual_v2.pdf"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60)

    print("== health ==")
    print(c.get("/health").json())

    print("\n== ingest v1 ==")
    r = c.post("/documents/ingest", json={"path": V1, "document_name": "CT-200 Manual"})
    r.raise_for_status()
    ing = r.json()
    doc_id = ing["document_id"]
    print(f"version {ing['version_no']}: {ing['node_count']} nodes, "
          f"{ing['added']} added; {len(ing['anomalies'])} anomalies")
    for a in ing["anomalies"]:
        print(f"   - {a['code']}: {a['detail']}")

    print("\n== top-level sections ==")
    for s in c.get(f"/documents/{doc_id}/sections").json():
        print(f"   {s['logical_key']:>4}  {s['heading']}")

    print("\n== search 'Error Codes' (duplicate headings) ==")
    hits = c.get(f"/documents/{doc_id}/search", params={"q": "Error Codes"}).json()
    for h in hits:
        print(f"   node {h['node_id']}  key={h['logical_key']}  {h['heading']}")
    n42 = [h for h in hits if h["logical_key"] == "4.2"][0]["node_id"]

    n32 = c.get(
        f"/documents/{doc_id}/search", params={"q": "Cuff Inflation"}
    ).json()[0]["node_id"]

    print("\n== create version-pinned selection (4.2 + 3.2, v1) ==")
    sel = c.post(
        "/selections",
        json={"name": "alarms + inflation", "node_ids": [n42, n32], "version_no": 1},
    ).json()
    print(f"   selection {sel['id']}  fingerprint={sel['fingerprint'][:12]}…")

    print("\n== generate QA test cases ==")
    gen = c.post("/generations", json={"selection_id": sel["id"]}).json()
    print(f"   status={gen['status']}  cases={len(gen['test_cases'])}  "
          f"idempotent={gen['idempotent_hit']}")
    for tc in gen["test_cases"]:
        print(f"   [{tc['id']}] ({tc['requirement_ref']}) {tc['title']}")

    again = c.post("/generations", json={"selection_id": sel["id"]}).json()
    print(f"   resubmit -> idempotent={again['idempotent_hit']} "
          f"(same id: {again['generation_id'] == gen['generation_id']})")

    print("\n== staleness before re-ingest ==")
    st = c.get(f"/generations/{gen['generation_id']}/staleness").json()
    print(f"   overall={st['overall']}")

    print("\n== re-ingest v2 ==")
    v2 = c.post(
        "/documents/ingest", json={"path": V2, "document_name": "CT-200 Manual"}
    ).json()
    print(f"   version {v2['version_no']}: added={v2['added']} modified={v2['modified']} "
          f"unchanged={v2['unchanged']} removed={v2['removed']}")

    print("\n== staleness after re-ingest ==")
    st = c.get(f"/generations/{gen['generation_id']}/staleness").json()
    print(f"   overall={st['overall']}")
    for s in st["sources"]:
        print(f"   {s['logical_key']:>12}  {s['status']:<9} {s['magnitude']:<6} "
              f"| {s['diff_summary']}")

    print("\n== cross-version change for 3.2 ==")
    ch = c.get(f"/nodes/{n32}/changes", params={"from": 1, "to": 2}).json()
    print(f"   {ch['status']}: {ch['diff_summary']}")
    for line in ch["changed_lines"][:4]:
        print(f"   {line}")

    print("\n== retrieval by node ==")
    for g in c.get("/generations", params={"node_id": n32}).json():
        print(f"   {g['generation_id']}  status={g['status']}  "
              f"cases={len(g['test_cases'])}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.ConnectError:
        print("Could not reach the API. Start it with:\n"
              "    uvicorn app.main:app --reload", file=sys.stderr)
        sys.exit(1)
