"""Model gateway interface.

The hub talks to language models only through this interface, so the model can be
swapped (self-hosted by default, a Canadian-region cloud model only if an administrator
enables it). An AI model only ever *drafts*; a human always decides.

Milestone 1 makes no LLM calls. ``NullGateway`` is the only implementation and it refuses
every request.

TODO(model-gateway): add a self-hosted implementation (e.g. an OpenAI-compatible endpoint
served inside the deployment) once the accuracy harness exists. No outbound calls.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class DraftRequest(BaseModel):
    """A request for the model to draft something for human review."""

    task: str = Field(description="Task identifier, e.g. 'draft-controls-from-clause'.")
    prompt: str
    language: str = Field(default="en", pattern="^(en|fr)$")


class DraftResponse(BaseModel):
    """A model draft. Never authoritative: always routed to a human reviewer."""

    text: str
    model_id: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@runtime_checkable
class ModelGateway(Protocol):
    """Swappable model gateway."""

    def draft(self, request: DraftRequest) -> DraftResponse:
        """Return a draft for human review."""
        ...


class NullGateway:
    """Placeholder gateway: Milestone 1 makes no LLM calls."""

    def draft(self, request: DraftRequest) -> DraftResponse:
        raise NotImplementedError("No model gateway is configured. Milestone 1 makes no LLM calls.")
