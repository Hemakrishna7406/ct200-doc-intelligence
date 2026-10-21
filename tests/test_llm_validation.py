"""Structured-output validation + retry/behaviour tests for the LLM layer."""

from __future__ import annotations

import json

from app.config import settings
from app.services.generation import parse_test_cases

VALID = {
    "test_cases": [
        {
            "id": "TC-1",
            "title": "Verify overpressure auto-deflate",
            "requirement_ref": "4.1",
            "preconditions": "Device idle",
            "steps": ["Exceed 299 mmHg"],
            "expected_result": "Deflates within 2 seconds",
            "priority": "high",
        },
        {
            "id": "TC-2",
            "title": "Verify E1 on disconnected cuff",
            "requirement_ref": "4.2",
            "preconditions": "Cuff removed",
            "steps": ["Start a measurement"],
            "expected_result": "Displays E1",
            "priority": "medium",
        },
        {
            "id": "TC-3",
            "title": "Verify low-battery icon",
            "requirement_ref": "2.1.1.1",
            "preconditions": "Battery below 15%",
            "steps": ["Power on"],
            "expected_result": "Low-battery icon shown",
            "priority": "low",
        },
    ]
}


def test_valid_json_parses():
    parsed, errors = parse_test_cases(json.dumps(VALID))
    assert parsed is not None and not errors
    assert len(parsed.test_cases) == 3


def test_code_fenced_json_parses():
    raw = "Here you go:\n```json\n" + json.dumps(VALID) + "\n```\n"
    parsed, errors = parse_test_cases(raw)
    assert parsed is not None, errors


def test_prose_without_json_fails_cleanly():
    parsed, errors = parse_test_cases("Sure! Here are some ideas: 1. do a thing")
    assert parsed is None
    assert errors


def test_wrong_case_count_is_rejected():
    bad = {"test_cases": VALID["test_cases"][:2]}  # only 2, contract wants 3-5
    parsed, errors = parse_test_cases(json.dumps(bad))
    assert parsed is None
    assert any("3-5" in e or "at least 3" in e for e in errors)


def test_malformed_provider_output_is_recorded_as_failed(ingested, monkeypatch):
    """When the provider never returns valid JSON, the generation is stored as
    ``failed`` with the raw response preserved — never silently dropped."""
    client, doc_id = ingested
    monkeypatch.setattr(settings, "llm_provider", "mock-bad")
    n = client.get(
        f"/documents/{doc_id}/search", params={"q": "Cuff Inflation"}
    ).json()[0]["node_id"]
    sel = client.post("/selections", json={"name": "s", "node_ids": [n]}).json()
    g = client.post("/generations", json={"selection_id": sel["id"]}).json()

    assert g["status"] == "failed"
    assert g["test_cases"] == []
    assert g["validation_errors"]
    assert g["raw_response"]
    assert g["attempts"] >= 1  # it retried before giving up


def test_prompt_version_participates_in_idempotency(ingested, monkeypatch):
    client, doc_id = ingested
    n = client.get(
        f"/documents/{doc_id}/search", params={"q": "Cuff Inflation"}
    ).json()[0]["node_id"]
    sel = client.post("/selections", json={"name": "s", "node_ids": [n]}).json()
    g1 = client.post("/generations", json={"selection_id": sel["id"]}).json()

    monkeypatch.setattr(settings, "prompt_version", "v2")
    g2 = client.post("/generations", json={"selection_id": sel["id"]}).json()
    assert g2["idempotent_hit"] is False
    assert g2["generation_id"] != g1["generation_id"]
    assert g2["prompt_version"] == "v2"
