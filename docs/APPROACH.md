# Approach Document — CT-200 Document Intelligence

Tri9T AI / AffineSurge — AI Engineering Internship Assignment

This document explains **what** was built, **why** each decision was made, and
**where the approach breaks**. It is written to be defended in an interview: the
parts I know are weak are called out explicitly.

---

## 1. The problem, restated

Turn the CT-200 manual (PDF) into a browsable, structured, **versioned** tree;
let users build **version-pinned selections**; generate QA test-case ideas with
an LLM; and — the hard part — tell a user whether a previously generated test
case still reflects the current document after the manual is re-versioned.

Two sample documents were provided: `ct200_manual.pdf` (v1) and
`ct200_manual_v2.pdf` (v2). A note in the data package clarified that the task
is to work **directly with the PDF** (the original brief mentioned a Markdown
file).

---

## 2. Data model

Two stores, because the two kinds of data have different shapes.

### 2.1 Relational store — SQLite + SQLAlchemy (`app/models.py`)

| Table | Role |
|-------|------|
| `documents` | a logical document, keyed by name (e.g. "CT-200 Manual") |
| `document_versions` | one row per ingested PDF: version no, source file, source hash, page count, `is_latest` |
| `nodes` | the **logical** node — stable across versions; identity is `(document_id, logical_key)` |
| `node_versions` | a node's **snapshot** in one version: heading, body, level, parent links, table JSON, `content_hash`, `change_status`, anomalies |
| `selections` | a named selection + a fingerprint |
| `selection_items` | `(node_id, node_version_id, content_hash)` — the version pin |

The single most important modelling decision: **separate `Node` (identity) from
`NodeVersion` (content).** A selection pins `node_version_id`, so it keeps
resolving to the exact text it was created against even after the document is
re-ingested. Staleness is then a hash comparison between the pinned snapshot and
the node's current snapshot.

`content_hash` is a SHA-256 over **normalised** text (see §5.1), not raw text —
so cosmetic differences never masquerade as real edits.

### 2.2 Document store — JSONL by default, MongoDB optional (`app/services/store.py`)

LLM generations are schemaless, append-only documents: raw response, retry
count, validation errors, and a snapshot of every source node used. A
document-oriented store fits this naturally. The default is an append-only JSONL
file with an in-memory index; the justification is that this is a single-node
deployment where a file is simpler to operate, inspect and diff than a database,
and the access patterns (get-by-id, scan-by-selection/node/fingerprint) are all
O(n) over a tiny collection. `MongoGenerationStore` implements the identical
interface for when it outgrows a file — swapping is a one-line config change and
nothing above the interface knows the difference.

---

## 3. Parsing approach — and why

**Chosen approach: text-layer-first extraction with a typographic heading model,
plus an OCR fallback that activates only for image-only pages.**

Why this and not "just run OCR on everything":

1. **The CT-200 PDFs carry a real text layer.** Running OCR over a clean text
   layer would *introduce* errors (mis-read digits in a medical device manual —
   the worst possible failure) rather than remove them.
2. **The text layer preserves typography** (font size and boldness per line),
   which is the strongest available signal for heading detection.
3. OCR is still implemented and isolated (`app/parsing/ocr.py`, Tesseract via
   `pytesseract`) and the extractor falls back to it for any page with fewer
   than `CT200_OCR_MIN_CHARS_PER_PAGE` characters. If no OCR engine is present,
   the page is **flagged with a warning rather than silently emitted as empty** —
   exposing unsupported cases beats hiding them.

Tables are extracted with PyMuPDF's `find_tables`, then **de-duplicated**: the
detector over-fires (it finds the real table *and* spurious sub-tables inside
it), so we keep the largest tables and drop any whose bounding box is contained
in an already-kept one, and require ≥2 rows and ≥2 columns.

Table cell text is removed from the prose stream (any line whose position falls
inside a table bbox) and re-emitted as a dedicated `table` child node — so the
spec table's cells never leak into section 2.1's body text.

### 3.1 Normalisation before hashing (`app/textutil.py`)

`clean_text` repairs PDF-font artefacts (ligatures `ﬁ`/`ﬀ`, curly quotes,
unicode dashes) while preserving whitespace structure. `normalize_text` goes
further and collapses **all** whitespace, including the newlines that appear
wherever the PDF wrapped a line or broke a page. Hashing the normalised form is
what makes "moved from the bottom of page 3 to the top of page 4" *not* a
content change. Only a real edit changes the hash.

---

## 4. Hierarchy reconstruction (`app/parsing/hierarchy.py`)

The pipeline is: `extract` (flat lines + tables, with size/bold/position) →
`classify` (heading vs body) → `reconstruct` (tree).

**The core rule: a line is a heading if it is *bold* and starts with a section
number; its *level* is the depth of that number (`len(number.split('.'))`), not
its font size.**

That single decision is what makes the parser survive this document. Font sizes
here are *not* a reliable level signal:

* `3.2 Cuff Inflation Sequence` is bold but rendered at **body** size (11 pt),
  while every other level-2 heading is 12.9 pt.
* `2.1.1.1 Battery Life…` is bold at 11 pt too — a *level-4* number.

Trusting font size for level mis-places both. Trusting the number gets both
right.

**Tree construction** is a depth-stack over the reading-order stream:

1. **Reorder by numeric key.** `3.4` physically precedes `3.3` in the PDF. Both
   are children of `3`; the tree presents 3.3 then 3.4, and the original physical
   position is preserved in `source_order`.
2. **Skipped level re-attaches to the nearest existing ancestor.** `2.1.1.1` has
   no `2.1.1` parent, so it hangs off `2.1` and is flagged `skipped_level`.
3. **Duplicate titles stay distinct.** `4.2 Error Codes` and `7.1 Error Codes`
   are two nodes with two parents — their numbers differ, so identity differs.
4. **Body is assembled across page boundaries.** Because classification runs on
   one merged reading-order stream, a paragraph split by a page break is rejoined
   rather than truncated.
5. **Numbered list items are not headings.** The classification list inside 3.3
   ("1. Normal: systolic < 120 …") is not bold, *and* a bare-integer heading is
   only accepted if it is the next expected top-level number (after `3.3`, the
   next expected top-level is `4`, so `1. Normal` is rejected). Two independent
   guards.

Every irregularity produces an **anomaly record** (code + detail) surfaced in
the ingest response and on the node — never silently "fixed".

### 4.1 Structural inconsistencies discovered in the PDF

| # | Irregularity | Example | Handling |
|---|--------------|---------|----------|
| 1 | Multi-line title | title spans 3 lines | leading non-heading lines joined into one `title` node |
| 2 | Out-of-order sections | `3.4` before `3.3` | stack + numeric re-sort; `out_of_order_section` anomaly |
| 3 | Skipped level | `2.1.1.1` under `2.1` | re-attach to nearest ancestor; `skipped_level` anomaly |
| 4 | Duplicate heading | `Error Codes` at 4.2 and 7.1 | distinct nodes; `duplicate_heading_title` anomaly |
| 5 | Inconsistent heading size | `3.2` at body size | level from number depth, not size |
| 6 | Tables | spec table (2.1), error table (4.2) | `find_tables` + dedupe → `table` child nodes; cells stripped from prose |
| 7 | Content across page breaks | 4-heading at page foot; 6.1 split across pages | merged reading-order stream; continuity preserved |
| 8 | Ligatures from the PDF font | `Cuﬀ`, `Inﬂation` | `clean_text` normalisation |
| 9 | List vs heading ambiguity | `1. Normal: …` inside 3.3 | bold + sequence guard |

---

## 5. What the first implementation got wrong (and how I found it)

An honest record of the debugging, because the brief explicitly rewards process
over a clean-looking result.

**5.1 Level from font size.** My first classifier assigned level from font size
(16.5 → level 1, 12.9 → level 2, 11 → level 3). Inspecting the tree, `3.2`
landed as a level-3 child of `2.2` and `2.1.1.1` landed as a level-3 sibling of
`2.2`. *How I caught it:* I printed the full tree with levels and read it against
the PDF. *Fix:* derive level from the number's depth.

**5.2 Search failed on ligatures.** `GET /search?q=Cuff Inflation` returned
nothing although the section clearly exists — the stored heading was
`Cuﬀ Inﬂation` with U+FB00/U+FB02 ligatures. *How I caught it:* the end-to-end
smoke run returned an empty list where I expected a hit. *Fix:* `clean_text` at
extraction time, plus normalising both sides of the search.

**5.3 A changed section reported as "unchanged".** Section `4.2` showed
`status: unchanged` between v1 and v2 even though its **error-code table**
changed (E3 deflate time, new E6 row) — because 4.2 has no body text of its own;
its content lives in the child table node. *How I caught it:* I diffed the two
PDFs by hand, knew 4.2's table had changed, and saw the API disagree. *Fix:*
introduced **effective/subtree content** (`app/services/tree.py`) — change
detection and generation now operate on a node plus its descendants. This was
the most important fix in the project.

**5.4 The LLM never saw the tables.** The same root cause: context assembly sent
only the selected node's own text, so selecting "4.2" sent the heading and
nothing else — the model was asked to write test cases about error codes it
could not see. *Fix:* selections expand to their full subtree; every node version
actually used is recorded as a source (`role: selected | descendant`), so
staleness is checked at the granularity of the text really sent.

**5.5 Malformed-output handling was implicit.** Early on, a bad LLM response
would either crash or be dropped. *Fix:* explicit `failed` generations with the
raw response preserved and validation errors recorded (§7).

---

## 6. Version-matching strategy — and where it breaks

Matching is attempted in priority order (`app/services/ingestion.py`):

1. **Exact numeric path** (`logical_key`). `4.2` in v2 ≡ `4.2` in v1. Primary key;
   covers the vast majority of nodes and all of this document's changes.
2. **Same parent + identical normalised heading.** Catches a section that was
   renumbered but not rewritten.
3. **Unique identical normalised heading anywhere.** Catches a section that
   moved to a different parent.
4. Otherwise the node is **new** (`added`); a node with no counterpart is marked
   `removed` (history retained, nothing deleted).

**Known failure modes** (called out because the brief asks for them):

* **Renumbering en masse.** If an editor inserts a new section 3 and renumbers
  4→5, 5→6, … then path matching breaks for every shifted section. Rule 2 saves
  those that kept their heading text and parent, but a section that was both
  renumbered *and* reworded would be seen as `removed` + `added` — losing its
  history and any staleness link.
* **Duplicate headings with no number.** Rules 2–3 rely on title uniqueness;
  this document has duplicate *titles* but distinct *numbers*, so it is safe
  here, but a doc with two identically-titled unnumbered sections would be
  ambiguous (we refuse the ambiguous match rather than guess).
* **Heavy rewording.** Matching is not fuzzy on titles (deliberately — fuzzy
  matching silently merges unrelated nodes). A section whose number and title
  both changed is treated as new.
* **Table identity.** Tables are keyed by `parent#tableN` (ordinal within the
  parent). Two tables in the same section that swap order would be mismatched.

---

## 7. LLM design — prompt, structured output, retries, idempotency

**Provider.** Any provider works; the default is an offline `mock` provider so
the whole system runs with no key, and OpenAI-compatible (Groq / OpenAI /
OpenRouter) plus Gemini adapters are included. Provider choice is explicitly
*not* the point — structured-output handling is.

**Structured contract.** The prompt (`app/llm/prompts.py`) instructs the model to
return **only** a JSON object matching a schema, and the response is validated
against a Pydantic model `TestCaseSet` (`app/schemas.py`): 3–5 test cases, each
with id, title, `requirement_ref`, preconditions, steps, expected result and
priority. The validator enforces the 3–5 count, non-empty steps, and a valid
priority — so "the model returned something plausible" is not good enough.

**When the model misbehaves** (the brief's explicit test):

1. Strip markdown fences / leading prose and extract the first `{…}` block.
2. Parse and validate.
3. On failure, **retry once with a repair prompt** that includes the specific
   validation error and the previous response (`CT200_LLM_MAX_RETRIES`, default 2
   attempts total).
4. If it still fails, store the generation with `status: "failed"`,
   `validation_errors` and the **raw response preserved** — a first-class,
   queryable outcome, not a dropped request or a 500.

**Idempotency policy** (the brief asks for one, and to defend it). A generation's
identity is `sha256` of the selection's `(node_id, node_version_id)` pairs, plus
`prompt_version`, `provider` and `model`. Submitting the same selection twice
returns the **cached** completed generation with `idempotent_hit: true`, rather
than paying for a second LLM call and creating a near-duplicate. Bumping
`CT200_PROMPT_VERSION` (or changing the model) produces a fresh generation,
because the fingerprint changes. `force: true` bypasses the cache for a deliberate
regeneration. The trade-off: two *different* selections that happen to resolve to
the same node versions correctly share a generation — that is intended.

---

## 8. Staleness / impact detection

Each generation stores the `content_hash` **and the full text** of every node
version it was built from. At retrieval time (`app/services/staleness.py`) each
source node is re-resolved to its **current** version:

* hashes equal → `current`
* hashes differ → `stale` (with a diff summary and a `minor`/`major` magnitude)
* node gone from the latest version → `missing`

Overall is `current` (all current), `stale` (all stale/missing), `missing`, or
`partially_stale` (a mix).

**Magnitude.** The staleness *decision* is binary (any hash change ⇒ stale).
Magnitude is advisory triage: if the **numeric tokens** in the text changed
(e.g. `40 mmHg` → `30 mmHg`, or a new E6 row), it is `major`; a pure wording
change is `minor`. I deliberately did **not** make magnitude gate the decision —
a one-word wording change *is* still stale, but the user can see it is `minor`.
Whether a one-word change *should* count the same as a changed pressure
threshold is a judgement call; my answer is "flag both, rank them differently".

---

## 9. Decision log (required)

**Q1 — What is most likely to silently give wrong results without erroring, and
how would you catch it?**

The **version matcher**. If it silently merges two different sections (or splits
one), every downstream staleness answer is wrong while every response still looks
healthy — no exception is ever raised. Concretely, the riskiest case is rule 3
(unique-heading match), which could attach a moved section to the wrong history.
I catch it by (a) preferring the numeric path and only falling back to title
matching when the path is absent, (b) refusing the ambiguous case (two candidate
titles ⇒ treat as new) instead of guessing, and (c) asserting invariants in
tests — e.g. "an unchanged section keeps its node id" — so a regression in
matching fails a test rather than quietly corrupting a staleness answer. What I
would add: an ingest-time report of every fuzzy match for human review.

**Q2 — Where did you choose simplicity over correctness for time, and what
breaks first in production?**

Two places. First, **table identity is positional** (`parent#tableN`) rather than
content-based, so two tables that swap order in a section would be mismatched —
this breaks first if the manual is edited in that way. Second, the **JSONL
generation store** rewrites the whole file on every write; fine at hundreds of
generations, but it is O(n) per write and not concurrency-safe across processes,
so it would break first under load (the `MongoGenerationStore` backend exists for
exactly this). A third, softer one: staleness is computed on demand by scanning
the store, not indexed, so retrieval cost grows with history.

**Q3 — Name one input you did not handle, and what the system does when it sees
it.**

**A scanned PDF with no text layer and no OCR engine installed.** The extractor
detects the low character count, tries OCR, and — if Tesseract is absent —
records an explicit warning (`page N: only X chars and no OCR engine available`)
and produces a page with no lines, rather than inventing content. So the failure
is *visible and attributable*, but it is still a failure: the user gets a
warning and a partial tree, not a parsed document. The second unhandled input is
a PDF whose headings are **not bold** — my classifier would treat every heading
as body text and produce a single flat node; nothing in the output would say
"the heading model did not match this document".

---

## 10. What I would do differently with more time

* **Content-based table identity** and a table-aware diff (cell-level, not
  line-level) so an added row reads as "+1 row" rather than a text diff.
* **Embedding-based node matching** for renumbered-and-reworded sections, with a
  human-review queue for low-confidence matches instead of a hard cut-off.
* **A real vector/RAG layer** for the generation step — retrieve the *most
  relevant* passages across the whole manual rather than just the selected
  subtree — and cite the retrieved spans back into each test case.
* **Auto-regeneration of stale test cases** (explicitly out of scope here) behind
  an approval step.
* **A proper OCR regression suite** with a synthetic image-only PDF, so the
  fallback path is actually exercised in CI.
* **Database migrations** (Alembic) and a Postgres option for the structured
  store.

---

## 11. How correctness was validated

* **8 parser unit tests** (`tests/test_parser_irregularities.py`), one per
  irregularity — including the two the brief names explicitly (duplicate heading
  ⇒ two distinct nodes with correct parents; out-of-order sections reordered).
* **5 versioning tests**, including "unchanged node keeps its id" and
  "version-pinned selection still resolves to v1 text after v2 is ingested".
* **5 staleness tests**, including the container/table case and idempotency.
* **6 LLM-validation tests**, including the malformed-output path.
* **3 API tests** driving the full v1 → v2 → staleness → retrieval flow.
* Manual cross-check: the v1/v2 text diff was read by hand and the parser's
  reported changes reconciled against it.

All 27 pass with `pytest`.
