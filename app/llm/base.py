"""Provider abstraction: one async ``complete()`` call, nothing else."""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, system: str, user: str) -> str:
        """Return the raw text response. May raise LLMError on transport failure."""
        ...


class LLMError(RuntimeError):
    """Raised when a provider call fails at the transport level."""
