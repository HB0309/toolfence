"""Pydantic models for target profiles (profiles/*.json).

A ``TargetProfile`` captures everything needed to run ToolFence against a
specific MCP target: nanobot config, surface path, health check URL, state
reset strategy, untrusted content injection strategy, agent persona, normal
task definition, tool-result task prompt, attack probe list, and the required
tool-prefix check.

Two discriminated unions reduce validation noise:

- ``StateResetConfig`` discriminated on ``strategy`` (``"sqlite_backup"`` |
  ``"fs_restore"`` | ``"none"``).
- ``InjectionConfig`` discriminated on ``strategy`` (``"sqlite_review"`` |
  ``"fs_canary_file"`` | ``"none"``).

Import boundary
---------------
This module belongs to ``toolfence/contracts/`` and must not import from
``toolfence/engine/``, ``toolfence/guard/``, ``toolfence/integration/``, or
any nanobot/LLM client.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# State reset configs (discriminated on "strategy")
# ---------------------------------------------------------------------------


class SqliteBackupReset(BaseModel):
    """Reset by backing up and restoring a SQLite database."""

    strategy: Literal["sqlite_backup"]
    db_path: str


class FsRestoreReset(BaseModel):
    """Reset by deleting and re-copying a folder from a snapshot."""

    strategy: Literal["fs_restore"]
    snapshot_path: str
    working_path: str


class NoReset(BaseModel):
    """No state reset between trials."""

    strategy: Literal["none"]


StateResetConfig = Annotated[
    Union[SqliteBackupReset, FsRestoreReset, NoReset],
    Field(discriminator="strategy"),
]


# ---------------------------------------------------------------------------
# Injection configs (discriminated on "strategy")
# ---------------------------------------------------------------------------


class SqliteReviewInjection(BaseModel):
    """Inject canary by inserting a row into a SQLite reviews table."""

    strategy: Literal["sqlite_review"]
    db_path: str
    table: str
    columns: dict[str, object]
    id_column: str


class FsCanaryFileInjection(BaseModel):
    """Inject canary by writing a file into a working directory."""

    strategy: Literal["fs_canary_file"]
    working_path: str
    filename: str


class NoInjection(BaseModel):
    """No injection (user-input channel only, or external injection)."""

    strategy: Literal["none"]


InjectionConfig = Annotated[
    Union[SqliteReviewInjection, FsCanaryFileInjection, NoInjection],
    Field(discriminator="strategy"),
]


# ---------------------------------------------------------------------------
# Normal task definition
# ---------------------------------------------------------------------------


class NormalTask(BaseModel):
    """The normal (non-attack) task definition for a profile."""

    prompt: str
    goal_tool: str
    label: str = "primary"


# ---------------------------------------------------------------------------
# Extra normal task (e.g. read_then_write for filesystem profile)
# ---------------------------------------------------------------------------


class ExtraNormalTask(BaseModel):
    """An additional normal task with a descriptive label and optional note."""

    label: str
    prompt: str
    goal_tool: str
    note: str | None = None


# ---------------------------------------------------------------------------
# Attack probe entry
# ---------------------------------------------------------------------------


class AttackProbeEntry(BaseModel):
    """An attack probe with an optional per-probe task_prompt override.

    Used when a probe needs a different task prompt from the profile-level
    ``tool_result_task_prompt`` (e.g. the taint-flow probe).
    """

    path: str
    task_prompt: str | None = None


# ---------------------------------------------------------------------------
# TargetProfile
# ---------------------------------------------------------------------------


class TargetProfile(BaseModel):
    """Full target profile loaded from ``profiles/<name>.json``.

    All path fields are relative to the repository root.
    """

    model_config = {"extra": "forbid"}

    profile_id: str
    description: str

    # nanobot config passed to _load_runtime_config
    nanobot_config: str

    # reviewed surface.json for Guard
    surface: str

    # optional HTTP GET health check; null skips it
    health_url: str | None = None

    # state reset strategy between trials
    state_reset: StateResetConfig

    # how to plant the canary for tool-result channel trials
    injection: InjectionConfig

    # persona written into AGENTS.md for the instructional defense
    agent_persona: str

    # primary normal task
    normal_task: NormalTask

    # additional normal tasks (e.g. read_then_write)
    extra_normal_tasks: list[ExtraNormalTask] = Field(default_factory=list)

    # prompt sent to the agent on tool-result channel trials
    tool_result_task_prompt: str

    # attack probe files (str path or object with optional task_prompt override)
    attack_probes: list[str | AttackProbeEntry]

    # regex prefix; NanobotAdapter aborts if no tool matches; null = skip check
    required_tool_prefix: str | None = None
