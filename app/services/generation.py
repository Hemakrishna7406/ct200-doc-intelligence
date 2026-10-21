"""LLM generation: context assembly, structured-output validation, retries,
idempotency, and persistence of the result linked to its exact source text.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import prompts
from app.llm.base import LLMError
from app.llm.providers import get_provider
from app.models import NodeVersion, Selection
from app.schemas import TestCaseSet
from app.services.store import get_store
from app.services.tree import subtree_node_versions


class GenerationError(RuntimeError):
    pass


def node_version_text(nv: NodeVersion) -> str:
    """Reconstruct the human-readable text of a node version (incl. tables)."""
    parts = [nv.heading]
    if nv.body_text:
        parts.append(nv.body_text)
    if nv.table_json:
        for row in nv.table_json:
            parts.append(" | ".join((c or "") for c in row))
    return "\n".join(p for p in parts if p)


def _strip_json(raw: str) -> str:
    """Pull the JSON object out of a possibly-chatty / fenced response."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_test_cases(raw: str) -> tuple[TestCaseSet | None, list[str]]:
    """Return (validated set | None, errors)."""
    try:
        data = json.loads(_strip_json(raw))
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON: {exc}"]
    try:
        return TestCaseSet.model_validate(data), []
    except ValidationError as exc:
        return None, [f"{e['loc']}: {e['msg']}" for e in exc.errors()]


def _build_context(db: Session, selection: Selection):
    """Assemble the text handed to the LLM, and the snapshot of what was used.

    Each selected node is expanded to its full subtree so that selecting a
    section like ``4.2`` also pulls in its error-code table. Every node version
    actually used is recorded as a source, so staleness is checked at the
    granularity of the text that was really sent.
    """
    sources = []
    refs = []
    blocks = []
    seen: set[int] = set()
    for item in selection.items:
        pinned = db.get(NodeVersion, item.node_version_id)
        if pinned is None:
            continue
        nvs = subtree_node_versions(db, item.node_id, pinned.document_version_id)
        for nv in nvs:
            if nv is None or nv.id in seen:
                continue
            seen.add(nv.id)
            text = node_version_text(nv)
            role = "selected" if nv.id == item.node_version_id else "descendant"
            sources.append(
                {
                    "node_id": nv.node_id,
                    "node_version_id": nv.id,
                    "logical_key": nv.number or nv.node.logical_key,
                    "heading": nv.heading,
                    "content_hash": nv.content_hash,
                    "role": role,
                    "text": text,
                    "text_excerpt": text[:200],
                }
            )
            if nv.number:
                refs.append(nv.number)
            blocks.append(f"[{nv.number or nv.node.logical_key}] {text}")
    section_text = "\n\n".join(blocks)
    return section_text, refs, sources


async def generate(db: Session, selection_id: int, force: bool = False) -> dict:
    selection = db.get(Selection, selection_id)
    if selection is None:
        raise GenerationError(f"selection {selection_id} not found")

    provider = get_provider()
    store = get_store()

    # --- idempotency ------------------------------------------------------- #
    if not force:
        for rec in store.all():
            if (
                rec.get("selection_fingerprint") == selection.fingerprint
                and rec.get("prompt_version") == settings.prompt_version
                and rec.get("provider") == provider.name
                and rec.get("model") == provider.model
                and rec.get("status") == "completed"
            ):
                out = dict(rec)
                out["idempotent_hit"] = True
                return out

    section_text, refs, sources = _build_context(db, selection)
    if not section_text.strip():
        raise GenerationError("selection resolves to empty text")

    system = prompts.SYSTEM_PROMPT
    user = prompts.build_user_prompt(section_text, refs)

    raw = ""
    errors: list[str] = []
    parsed: TestCaseSet | None = None
    attempts = 0
    max_attempts = max(1, settings.llm_max_retries + 1)

    while attempts < max_attempts and parsed is None:
        attempts += 1
        try:
            raw = await provider.complete(system, user)
        except LLMError as exc:
            errors.append(f"provider error: {exc}")
            break
        parsed, errors = parse_test_cases(raw)
        if parsed is None and attempts < max_attempts:
            user = prompts.build_repair_prompt(raw, "; ".join(errors))

    record = {
        "generation_id": str(uuid.uuid4()),
        "selection_id": selection.id,
        "selection_fingerprint": selection.fingerprint,
        "prompt_version": settings.prompt_version,
        "provider": provider.name,
        "model": provider.model,
        "status": "completed" if parsed is not None else "failed",
        "attempts": attempts,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "test_cases": [tc.model_dump() for tc in parsed.test_cases] if parsed else [],
        "validation_errors": [] if parsed else errors,
        "raw_response": raw,
        "sources": sources,
    }
    store.save(record)
    out = dict(record)
    out["idempotent_hit"] = False
    return out
