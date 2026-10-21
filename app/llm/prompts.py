"""Prompt design for QA test-case generation.

Kept in one place so the prompt can be versioned (``CT200_PROMPT_VERSION``) and
so the structured-output contract is visible next to the instructions that ask
for it.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are a senior QA engineer for medical-device software.
You write precise, executable test cases for a blood-pressure monitor and you
trace every test case back to the requirement it came from.

Rules:
- Return ONLY a JSON object. No prose, no markdown, no code fences.
- The JSON must match this schema exactly:
  {
    "test_cases": [
      {
        "id": "TC-1",
        "title": "short imperative title",
        "requirement_ref": "the section number, e.g. 4.2",
        "preconditions": "state the device/system state before the test",
        "steps": ["step 1", "step 2"],
        "expected_result": "the observable, checkable outcome",
        "priority": "low" | "medium" | "high"
      }
    ],
    "notes": "optional short note"
  }
- Produce between 3 and 5 test cases.
- Each test case must be concrete enough that another engineer could run it
  without asking questions, and must cite a requirement_ref that appears in the
  supplied text.
"""


def build_user_prompt(section_text: str, refs: list[str]) -> str:
    ref_list = ", ".join(refs) if refs else "(none)"
    return (
        "Generate QA test-case ideas for the following manual sections.\n"
        f"Available requirement references: {ref_list}\n\n"
        "--- BEGIN MANUAL TEXT ---\n"
        f"{section_text}\n"
        "--- END MANUAL TEXT ---\n\n"
        "Return the JSON object described in the system prompt."
    )


def build_repair_prompt(previous: str, error: str) -> str:
    """Second-chance prompt used when the first response failed validation."""
    return (
        "Your previous response could not be parsed as valid JSON matching the "
        f"schema. Error: {error}\n\n"
        "Here is the previous response:\n"
        f"{previous[:2000]}\n\n"
        "Return ONLY a corrected JSON object that matches the schema. "
        "No prose, no code fences."
    )


def dumps_schema() -> str:
    from app.schemas import TestCaseSet

    return json.dumps(TestCaseSet.model_json_schema(), indent=2)
