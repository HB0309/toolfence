"""Pydantic models for the tool-surface map (results/surface.json)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# SHA-256 of a tool description: exactly 64 lowercase hex characters.
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SurfaceEntry(BaseModel):
    """One row in the surface map — one reviewed tool."""

    model_config = {"extra": "forbid"}

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    route: str                                      # e.g. "POST /cancel/{booking_id}"
    action_class: Literal["read", "state-changing", "irreversible"]
    trust_label: Literal["first-party", "untrusted"]
    description_sha256: Sha256Hex                   # SHA-256 of the tool description at review time


class SurfaceFile(BaseModel):
    """Top-level surface.json document."""

    model_config = {"extra": "forbid"}

    version: Literal[1]
    tools: list[SurfaceEntry]
