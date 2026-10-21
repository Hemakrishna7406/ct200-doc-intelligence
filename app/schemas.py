"""Pydantic schemas: API request/response bodies and the LLM structured output."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------- #
# Parsing / ingestion
# --------------------------------------------------------------------------- #


class Anomaly(BaseModel):
    code: str
    detail: str
    node_key: str | None = None


class IngestRequest(BaseModel):
    path: str = Field(..., description="Path to the PDF on the server filesystem")
    document_name: str = Field(..., description="Logical document name (groups versions)")
    version_no: int | None = Field(
        None, description="Explicit version number; auto-increments if omitted"
    )
    notes: str | None = None


class NodeOut(BaseModel):
    node_id: int
    node_version_id: int
    logical_key: str
    number: str | None
    heading: str
    level: int
    kind: str
    content_hash: str
    change_status: str
    has_children: bool = False
    anomalies: list[str] = []


class NodeDetail(NodeOut):
    body_text: str
    table: list[list[str | None]] | None = None
    parent_node_id: int | None = None
    children: list[NodeOut] = []


class DocumentVersionOut(BaseModel):
    id: int
    version_no: int
    source_filename: str
    page_count: int
    is_latest: bool
    ingested_at: datetime
    notes: str | None = None


class IngestResult(BaseModel):
    document_id: int
    document_name: str
    version_id: int
    version_no: int
    node_count: int
    added: int
    modified: int
    unchanged: int
    removed: int
    anomalies: list[Anomaly] = []


class ChangeOut(BaseModel):
    node_id: int
    logical_key: str
    heading: str
    status: Literal["unchanged", "modified", "added", "removed"]
    from_version: int | None = None
    to_version: int
    diff_summary: str | None = None
    changed_lines: list[str] = []


# --------------------------------------------------------------------------- #
# Selections
# --------------------------------------------------------------------------- #


class SelectionCreate(BaseModel):
    name: str
    node_ids: list[int] = Field(..., min_length=1)
    version_no: int | None = Field(
        None, description="Pin to this version; defaults to the document's latest"
    )


class SelectionItemOut(BaseModel):
    node_id: int
    node_version_id: int
    logical_key: str
    heading: str
    content_hash: str


class SelectionOut(BaseModel):
    id: int
    name: str
    fingerprint: str
    created_at: datetime
    items: list[SelectionItemOut]


# --------------------------------------------------------------------------- #
# LLM generation — the structured contract the model MUST satisfy
# --------------------------------------------------------------------------- #


class TestCase(BaseModel):
    """A single QA test case idea produced from a selection."""

    id: str = Field(..., description="Short stable id, e.g. TC-1")
    title: str = Field(..., min_length=3)
    requirement_ref: str = Field(
        ..., description="The section/number the case traces back to, e.g. '4.2'"
    )
    preconditions: str = Field(..., min_length=3)
    steps: list[str] = Field(..., min_length=1)
    expected_result: str = Field(..., min_length=3)
    priority: Literal["low", "medium", "high"] = "medium"

    @field_validator("steps")
    @classmethod
    def _non_empty_steps(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("steps must contain at least one non-empty step")
        return cleaned


class TestCaseSet(BaseModel):
    """Top-level structured-output contract."""

    test_cases: list[TestCase] = Field(..., min_length=1, max_length=8)
    notes: str | None = None

    @field_validator("test_cases")
    @classmethod
    def _count(cls, v: list[TestCase]) -> list[TestCase]:
        if not (3 <= len(v) <= 5):
            raise ValueError("expected 3-5 test cases")
        return v


class GenerateRequest(BaseModel):
    selection_id: int
    force: bool = Field(
        False,
        description=(
            "Regenerate even if an identical generation already exists. "
            "Default false = idempotent: repeat submissions return the cached one."
        ),
    )


class SourceSnapshot(BaseModel):
    node_id: int
    node_version_id: int
    logical_key: str
    heading: str
    content_hash: str
    text_excerpt: str
    role: Literal["selected", "descendant"] = "selected"


class GenerationOut(BaseModel):
    generation_id: str
    selection_id: int
    selection_fingerprint: str
    prompt_version: str
    provider: str
    model: str
    status: Literal["completed", "failed"]
    idempotent_hit: bool = False
    attempts: int = 1
    created_at: datetime
    test_cases: list[TestCase] = []
    validation_errors: list[str] = []
    raw_response: str | None = None
    sources: list[SourceSnapshot] = []


# --------------------------------------------------------------------------- #
# Staleness / retrieval
# --------------------------------------------------------------------------- #


class SourceStatus(BaseModel):
    node_id: int
    logical_key: str
    heading: str
    status: Literal["current", "stale", "missing"]
    magnitude: Literal["none", "minor", "major"] = "none"
    generated_from_hash: str
    current_hash: str | None = None
    diff_summary: str | None = None
    role: Literal["selected", "descendant"] = "selected"


class StalenessOut(BaseModel):
    generation_id: str
    overall: Literal["current", "stale", "partially_stale", "missing"]
    checked_at: datetime
    sources: list[SourceStatus]


class GenerationListItem(BaseModel):
    generation_id: str
    selection_id: int
    status: str
    created_at: datetime
    test_case_count: int
