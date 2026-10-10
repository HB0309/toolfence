"""Pydantic models for evaluation trace documents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


# Valid provenance labels — used as the value type of TraceEntry.provenance so
# the constraint appears in both Pydantic validation and the generated JSON Schema.
ProvenanceLabel = Literal["user", "first-party", "untrusted"]


class UsageInfo(BaseModel):
    """Token and timing usage reported by the model host."""

    model_config = {"extra": "forbid"}

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    generation_ms: int


class TraceEntry(BaseModel):
    """One tool call recorded during an agent turn."""

    model_config = {"extra": "forbid"}

    name: str
    params: dict[str, Any]
    result: str | None
    error: str | None
    duration_ms: int
    provenance: dict[str, ProvenanceLabel]  # param name → "user" | "first-party" | "untrusted"
    guard_decision: Literal["pass", "hold"]


class Trace(BaseModel):
    """Full trace document returned by an adapter for one agent turn."""

    model_config = {"extra": "forbid"}

    run_id: str
    session_key: str
    model: str
    host: str
    timestamp: str          # ISO-8601 string; not parsed to datetime to keep the schema simple
    status: Literal["ok", "error", "timeout", "max_iterations"]
    final_reply: str | None
    tool_calls: list[TraceEntry]
    usage: UsageInfo
