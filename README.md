# CT-200 Document Intelligence

A backend that turns the **CardioTrack CT-200 Home Blood Pressure Monitor** manual
(PDF) into a browsable, versioned, structured tree; lets a user build
version-pinned *selections*; generates QA test-case ideas from those selections
with an LLM; and tells the user when a previously generated test case has gone
**stale** because the underlying document text changed.

Built for the Tri9T AI / AffineSurge AI Engineering Internship assignment.

---

## What it does

| # | Capability | Where |
|---|------------|-------|
| 1 | **Ingestion & structuring** — PDF → hierarchical tree, each node keeps heading, level, body, parent/child links and a content hash | `app/parsing/` |
| 2 | **Versioning** — re-ingest `v2` as a new version; unchanged nodes keep their identity, edited nodes are flagged | `app/services/ingestion.py` |
| 3 | **Browse API** — top-level sections, node detail, search, cross-version change + diff | `app/routers/nodes.py`, `app/services/browse.py` |
| 4 | **Selection API** — named, **version-pinned** sets of node versions | `app/services/selection.py` |
| 5 | **Generation API** — 3–5 QA test cases from a selection, with structured-output validation + retry | `app/services/generation.py`, `app/llm/` |
| 6 | **Staleness / impact** — is a generation still valid against the latest document? | `app/services/staleness.py` |
| 7 | **Retrieval API** — fetch generations by selection id or node id | `app/routers/generations.py` |

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; sensible defaults are baked in

# run the API
uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
```

Then, in another shell, drive the whole v1 → v2 → staleness flow:

```bash
python scripts/e2e_demo.py       # hits the running server
# or, with no server:
python scripts/smoke_test.py
```

### Run the tests

```bash
pytest            # 27 tests: parser irregularities, versioning, staleness, LLM validation, API
```

---

## The two sample documents

`data/ct200_manual.pdf` (v1, 6 pages) and `data/ct200_manual_v2.pdf` (v2, 7 pages)
are the provided CT-200 manual. v2 differs from v1 in exactly five ways:

| Change | Node |
|--------|------|
| battery life 300 → **250** cycles; icon threshold 15% → **10%** | 2.1.1.1 |
| inflation increment 40 → **30** mmHg (+ explanatory sentence) | 3.2 |
| error table: E3 deflate 2 s → **1.5 s**; new **E6** row | 4.2 (table) |
| alarm thresholds now cover **E1–E6** | 4.3 |
| new section **5.3 Data Export** | 5.3 |

The parser is not told any of this; it rediscovers it structurally.

---

## How to trigger the v1 → v2 re-ingestion flow

Ingestion is keyed on a **document name** — the same name groups versions.

```bash
# 1. ingest v1  (creates document "CT-200 Manual", version 1)
curl -s localhost:8000/documents/ingest -H 'content-type: application/json' \
  -d '{"path":"data/ct200_manual.pdf","document_name":"CT-200 Manual"}'

# 2. browse / select / generate against v1 ...

# 3. ingest v2  (same name -> version 2, nothing from v1 is destroyed)
curl -s localhost:8000/documents/ingest -H 'content-type: application/json' \
  -d '{"path":"data/ct200_manual_v2.pdf","document_name":"CT-200 Manual"}'

# 4. re-check a generation's staleness
curl -s localhost:8000/generations/<GENERATION_ID>/staleness
```

`python scripts/e2e_demo.py` does all of the above and prints the result.

---

## API reference

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/documents/ingest` | Parse a PDF into a new document version |
| `GET`  | `/documents` | List documents + versions |
| `GET`  | `/documents/{id}/versions` | List versions of a document |
| `GET`  | `/documents/{id}/sections?version=` | Top-level sections (default: latest) |
| `GET`  | `/documents/{id}/search?q=&version=` | Search headings + body |
| `GET`  | `/nodes/{node_id}?version=` | Node detail: children, full text, hash |
| `GET`  | `/nodes/{node_id}/changes?from=&to=` | Cross-version status + diff summary |
| `POST` | `/selections` | Create a version-pinned selection |
| `GET`  | `/selections/{id}` | Fetch a selection |
| `POST` | `/generations` | Generate QA test cases from a selection |
| `GET`  | `/generations?selection_id=&node_id=` | Retrieve generations |
| `GET`  | `/generations/{id}` | Fetch one generation |
| `GET`  | `/generations/{id}/staleness` | Is it still valid? |

Full interactive docs at `/docs`.

---

## Configuration (`.env`)

All variables are optional; see `.env.example`. The important ones:

| Variable | Default | Meaning |
|----------|---------|---------|
| `CT200_DATABASE_URL` | `sqlite:///./ct200.db` | Structured store (tree, versions, selections) |
| `CT200_GENERATION_STORE` | `json` | `json` (default) or `mongo` for the LLM-output store |
| `CT200_GENERATION_STORE_PATH` | `./data/generations.jsonl` | JSON store path |
| `CT200_LLM_PROVIDER` | `mock` | `mock` \| `openai` \| `groq` \| `openrouter` \| `gemini` |
| `CT200_LLM_MODEL` | `llama-3.1-8b-instant` | Model name |
| `CT200_LLM_API_KEY` | — | Provider key |
| `CT200_PROMPT_VERSION` | `v1` | Bump to invalidate generation caches |
| `CT200_OCR_ENABLED` | `true` | Enable the OCR fallback for image-only pages |

**No API key needed to run.** The default `mock` provider returns deterministic,
schema-valid output so the entire pipeline (including staleness) runs offline.
Point `CT200_LLM_PROVIDER` at a real provider to use a live model — the
structured-output validation, retry and failure handling are identical either way.

---

## Architecture

```
PDF ──▶ extract ──▶ classify ──▶ hierarchy ──▶ ingest ──▶ SQLite
        (text +     (headings)   (tree +       (version    (documents,
         tables +                 anomalies)    matching)   versions, nodes,
         OCR fallback)                                       node_versions,
                                                             selections)
                                                                    │
   selection ──▶ subtree text ──▶ LLM ──▶ validate/retry ──▶ JSON store
                                          (structured output)  (generations,
                                                                source snapshots)
                                                                    │
                        staleness check  ◀── re-ingest v2 ───────────┘
```

* **Structured store (SQLite + SQLAlchemy)** holds the tree, versions and
  selections — relational, transactional, easy to query.
* **LLM output store (JSONL by default, MongoDB optional)** holds generations —
  schemaless, append-only documents whose shape (raw response, retries,
  validation errors, source snapshots) suits a document store.
* Every generation records the **content hash of the exact text it was built
  from**, which is what makes staleness detection possible.

See [`docs/APPROACH.md`](docs/APPROACH.md) for the data model, the parsing
decisions behind each irregularity, the version-matching strategy and its
failure modes, the LLM prompt/validation design, and the required decision log.

---

## Project layout

```
app/
  main.py                 FastAPI app + routers
  config.py database.py models.py schemas.py textutil.py
  parsing/
    ocr.py                OCR adapter (tesseract, optional)
    extract.py            PDF text/tables + OCR fallback
    hierarchy.py          heading classification + tree reconstruction
  services/
    ingestion.py          parse -> persist + version matching
    browse.py             read queries (sections, search, changes)
    tree.py               subtree/effective-content helpers
    selection.py          version-pinned selections
    generation.py         context assembly, validation, retries, idempotency
    staleness.py          impact detection
    diffing.py            diff summary + change magnitude
    store.py              JSON / Mongo generation store
  llm/
    base.py providers.py prompts.py
  routers/
    documents.py nodes.py selections.py generations.py
data/                     ct200_manual.pdf, ct200_manual_v2.pdf
docs/APPROACH.md          approach document + decision log
scripts/                  e2e_demo.py, smoke_test.py, api_examples.sh
tests/                    parser, versioning, staleness, llm, api
```

---

## Notes & honest limitations

* The CT-200 PDFs carry a real text layer, so the pipeline is **text-layer
  first** with an OCR fallback that activates only for image-only pages. The OCR
  path is implemented and isolated (`app/parsing/ocr.py`) but is not exercised by
  these documents — see the approach doc.
* Change detection is **binary on content hash** (any edit ⇒ stale); a
  `minor`/`major` *magnitude* is reported as an advisory signal, not used in the
  decision.
* The parser is tuned for *this* document's irregularities, not general PDFs —
  which is exactly what the brief asked for.
