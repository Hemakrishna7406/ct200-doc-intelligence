"""NoSQL store for LLM-generated output.

Generations are stored **separately from the relational tree** because they are
schemaless, append-only artifacts whose shape (raw response, retries, validation
errors, snapshots) is naturally document-oriented. Two backends:

* ``JsonGenerationStore`` (default) — an append-only JSONL file with an in-memory
  index. Justification: single-node deployment, no ops overhead, trivially
  inspectable and diffable, and the access patterns here (get by id, scan by
  selection/node/fingerprint) are all O(n) over a tiny collection.
* ``MongoGenerationStore`` — same interface against MongoDB (local/Atlas) for
  when this outgrows a file. Selected with ``CT200_GENERATION_STORE=mongo``.

Swapping backends is a config change; nothing above this module knows which is
in use.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol

from app.config import settings


class GenerationStore(Protocol):
    def save(self, record: dict[str, Any]) -> None: ...
    def get(self, generation_id: str) -> dict[str, Any] | None: ...
    def update(self, generation_id: str, patch: dict[str, Any]) -> None: ...
    def all(self) -> list[dict[str, Any]]: ...


class JsonGenerationStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._records[rec["generation_id"]] = rec

    def _rewrite(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for rec in self._records.values():
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, self._path)

    def save(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records[record["generation_id"]] = record
            self._rewrite()

    def get(self, generation_id: str) -> dict[str, Any] | None:
        return self._records.get(generation_id)

    def update(self, generation_id: str, patch: dict[str, Any]) -> None:
        with self._lock:
            rec = self._records.get(generation_id)
            if rec is None:
                return
            rec.update(patch)
            self._rewrite()

    def all(self) -> list[dict[str, Any]]:
        return list(self._records.values())


class MongoGenerationStore:
    """MongoDB backend. Imported lazily so pymongo is optional."""

    def __init__(self, uri: str, db_name: str) -> None:  # pragma: no cover
        from pymongo import MongoClient  # type: ignore

        self._client = MongoClient(uri)
        self._col = self._client[db_name]["generations"]
        self._col.create_index("selection_id")
        self._col.create_index("selection_fingerprint")

    def save(self, record: dict[str, Any]) -> None:  # pragma: no cover
        self._col.replace_one(
            {"generation_id": record["generation_id"]}, record, upsert=True
        )

    def get(self, generation_id: str) -> dict[str, Any] | None:  # pragma: no cover
        doc = self._col.find_one({"generation_id": generation_id}, {"_id": 0})
        return doc

    def update(self, generation_id: str, patch: dict[str, Any]) -> None:  # pragma: no cover
        self._col.update_one({"generation_id": generation_id}, {"$set": patch})

    def all(self) -> list[dict[str, Any]]:  # pragma: no cover
        return list(self._col.find({}, {"_id": 0}))


_store: GenerationStore | None = None


def get_store() -> GenerationStore:
    global _store
    if _store is None:
        if settings.generation_store == "mongo":
            _store = MongoGenerationStore(settings.mongo_uri, settings.mongo_db)
        else:
            _store = JsonGenerationStore(settings.generation_store_path)
    return _store


def reset_store() -> None:
    """Test hook: drop the cached store so a new path takes effect."""
    global _store
    _store = None
