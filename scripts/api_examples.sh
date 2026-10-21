# Handy curl examples. Start the server first: uvicorn app.main:app --reload

BASE=http://127.0.0.1:8000

# --- ingest v1 -------------------------------------------------------------
curl -s $BASE/documents/ingest -H 'content-type: application/json' \
  -d '{"path":"data/ct200_manual.pdf","document_name":"CT-200 Manual"}'

# --- browse top-level sections (latest) ------------------------------------
curl -s "$BASE/documents/1/sections"

# --- browse a specific version ---------------------------------------------
curl -s "$BASE/documents/1/sections?version=1"

# --- search ----------------------------------------------------------------
curl -s "$BASE/documents/1/search?q=overpressure"

# --- node detail -----------------------------------------------------------
curl -s "$BASE/nodes/19"

# --- create a version-pinned selection -------------------------------------
curl -s $BASE/selections -H 'content-type: application/json' \
  -d '{"name":"alarms","node_ids":[19],"version_no":1}'

# --- generate --------------------------------------------------------------
curl -s $BASE/generations -H 'content-type: application/json' \
  -d '{"selection_id":1}'

# --- re-ingest v2 ----------------------------------------------------------
curl -s $BASE/documents/ingest -H 'content-type: application/json' \
  -d '{"path":"data/ct200_manual_v2.pdf","document_name":"CT-200 Manual"}'

# --- staleness of a generation ---------------------------------------------
curl -s "$BASE/generations/<GENERATION_ID>/staleness"

# --- cross-version change for a node ---------------------------------------
curl -s "$BASE/nodes/19/changes?from=1&to=2"

# --- retrieval by node / selection -----------------------------------------
curl -s "$BASE/generations?node_id=19"
curl -s "$BASE/generations?selection_id=1"
