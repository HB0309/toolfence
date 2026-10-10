"""Reusable adapter contract test suite.

Any concrete AgentAdapter implementation can be tested against this suite.
Import ``run_adapter_contract`` in your test module and call it with a
pre-built adapter instance.

Contract assertions (BASE-5, ENG-10):
  1. run_turn() returns a Trace instance.
  2. The returned Trace is valid against the Trace Pydantic schema (i.e. no
     ValidationError was raised during construction or copy).
  3. status is one of the four allowed literals.
  4. tool_calls is a list (may be empty).
  5. usage carries non-negative token counts.
  6. run_id and session_key are non-empty strings.

Note: determinism (same answer on every call) is NOT part of this contract
because live adapters such as NanobotAdapter produce different traces each
run.  Determinism is tested separately in test_scripted_adapter.py.
"""

from __future__ import annotations

from toolfence.contracts.trace import Trace
from toolfence.engine.adapter import AgentAdapter

_ALLOWED_STATUSES = {"ok", "error", "timeout", "max_iterations"}

# Dummy prompt / defense used by the contract suite; adapters must accept any
# string values here (ScriptedAdapter ignores them; live adapters use them).
_DUMMY_PROMPT = "Book the cheapest economy seat from Earth to Mars for Alice."
_DUMMY_DEFENSE = "none"


def run_adapter_contract(adapter: AgentAdapter) -> None:
    """Run all contract assertions against *adapter*.

    Call this function from a pytest test function::

        def test_my_adapter_contract() -> None:
            adapter = MyAdapter(...)
            run_adapter_contract(adapter)

    Raises ``AssertionError`` on any contract violation.
    """
    trace = adapter.run_turn(_DUMMY_PROMPT, _DUMMY_DEFENSE)

    # 1. Returns a Trace instance.
    assert isinstance(trace, Trace), (
        f"run_turn() must return a Trace; got {type(trace)!r}"
    )

    # 2. Re-validate through Pydantic to ensure the object is schema-valid.
    #    model_validate(model.model_dump()) round-trips through the validator.
    Trace.model_validate(trace.model_dump())

    # 3. status is a permitted literal.
    assert trace.status in _ALLOWED_STATUSES, (
        f"Trace.status {trace.status!r} is not one of {_ALLOWED_STATUSES}"
    )

    # 4. tool_calls is a list.
    assert isinstance(trace.tool_calls, list), (
        "Trace.tool_calls must be a list"
    )

    # 5. usage token counts are non-negative integers.
    u = trace.usage
    for field_name in ("input_tokens", "output_tokens", "reasoning_tokens",
                        "total_tokens", "generation_ms"):
        value = getattr(u, field_name)
        assert isinstance(value, int) and value >= 0, (
            f"usage.{field_name} must be a non-negative int; got {value!r}"
        )

    # 6. run_id and session_key are non-empty strings.
    assert isinstance(trace.run_id, str) and trace.run_id, (
        "Trace.run_id must be a non-empty string"
    )
    assert isinstance(trace.session_key, str) and trace.session_key, (
        "Trace.session_key must be a non-empty string"
    )

