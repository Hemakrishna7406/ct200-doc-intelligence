"""Concrete LLM providers.

* ``MockProvider`` — deterministic, offline. Produces a valid ``TestCaseSet``
  from whatever section numbers it can see, so the entire pipeline (including
  staleness) is runnable and testable with **no API key**. This is the default.
* ``OpenAICompatibleProvider`` — Groq / OpenAI / OpenRouter (all expose the
  ``/chat/completions`` shape).
* ``GeminiProvider`` — Google Generative Language ``generateContent``.

All three return raw text; parsing + validation happens one layer up in
``services.generation`` so every provider gets the same structured-output
guarantees.
"""

from __future__ import annotations

import json
import re

import httpx

from app.config import settings
from app.llm.base import LLMError

_NUM_RE = re.compile(r"\b(\d+(?:\.\d+)+|\d+)\b")


class MockProvider:
    """Offline, deterministic provider used by tests and local demos."""

    name = "mock"

    def __init__(self, model: str = "mock-qa-1") -> None:
        self.model = model

    async def complete(self, system: str, user: str) -> str:
        refs: list[str] = []
        line = ""
        for ln in user.splitlines():
            if ln.startswith("Available requirement references:"):
                line = ln.split(":", 1)[1]
                break
        for m in _NUM_RE.findall(line):
            if m not in refs:
                refs.append(m)
        refs = refs[:5] or ["1"]
        # always emit exactly 3 cases so the structured contract is satisfied
        # even when the selection has only one section
        pick = (refs * 3)[:3]
        cases = []
        for i, ref in enumerate(pick, start=1):
            cases.append(
                {
                    "id": f"TC-{i}",
                    "title": f"Verify behaviour described in section {ref}",
                    "requirement_ref": ref,
                    "preconditions": "Device powered on, self-test passed.",
                    "steps": [
                        "Put the device in the state described by the section.",
                        "Perform the action described by the section.",
                    ],
                    "expected_result": (
                        f"The device behaves exactly as specified in section {ref}."
                    ),
                    "priority": "high" if i == 1 else "medium",
                }
            )
        return json.dumps({"test_cases": cases, "notes": "generated offline (mock)"})


class _MalformedMockProvider:
    """Deliberately returns junk — used to exercise the retry/failure path."""

    name = "mock-bad"

    def __init__(self, model: str = "mock-bad-1") -> None:
        self.model = model

    async def complete(self, system: str, user: str) -> str:
        return "Sure! Here are some test cases:\n1. do a thing\n2. hope it works"


class OpenAICompatibleProvider:
    def __init__(
        self, name: str, model: str, api_key: str, base_url: str, timeout: float
    ) -> None:
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network dependent
            raise LLMError(f"{self.name} request failed: {exc}") from exc
        return data["choices"][0]["message"]["content"]


class GeminiProvider:
    def __init__(self, model: str, api_key: str, timeout: float) -> None:
        self.name = "gemini"
        self.model = model
        self._api_key = api_key
        self._timeout = timeout

    async def complete(self, system: str, user: str) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self._api_key}"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network dependent
            raise LLMError(f"gemini request failed: {exc}") from exc
        return data["candidates"][0]["content"]["parts"][0]["text"]


_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def get_provider(name: str | None = None) -> object:
    """Factory returning a provider instance for the configured name."""
    name = (name or settings.llm_provider).lower()
    if name == "mock":
        return MockProvider()
    if name == "mock-bad":
        return _MalformedMockProvider()
    if name in _BASE_URLS:
        base = settings.llm_base_url or _BASE_URLS[name]
        return OpenAICompatibleProvider(
            name=name,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=base,
            timeout=settings.llm_timeout,
        )
    if name == "gemini":
        return GeminiProvider(
            model=settings.llm_model or "gemini-1.5-flash",
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout,
        )
    raise LLMError(f"unknown LLM provider: {name!r}")
