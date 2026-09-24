"""Public vs private boundary for RB01.

The agent may see the traveler message and tool return payloads only.
Grading secrets from task.json must never appear in any tool output.
"""
from __future__ import annotations

from typing import Any, Iterable

# Fields on task.json that the grader may read and tools must never expose.
PRIVATE_TASK_KEYS = frozenset(
    {
        "verifiers",
        "reference_booking",
        "expected_total",
        "hidden_info",
        "traps",
        "constraints",
        "planted_ambiguity",
        "difficulty_levers",
        "meeting",
    }
)

# Exact labels that must not appear as JSON keys or free text in tool payloads.
PRIVATE_KEY_NAMES = frozenset(
    {
        "verifiers",
        "reference_booking",
        "expected_total",
        "hidden_info",
        "traps",
        "constraints",
        "planted_ambiguity",
        "difficulty_levers",
        "pass_condition",
        "check_type",
        "critical",
    }
)

# Episode fields the environment may use (ask-traveler scripting, identity).
# These are not grading answers.
PUBLIC_TASK_KEYS = frozenset(
    {
        "task_id",
        "scenario_family",
        "route",
        "travel_date",
        "traveler_id",
        "snapshot_id",
        "user_message",
        "scripted_replies",
        "default_reply",
        "finalize_reply",
        "max_clarifications",
    }
)


def public_task_view(task: dict) -> dict:
    """Agent/env-facing slice of task.json — no grading secrets."""
    return {k: task[k] for k in PUBLIC_TASK_KEYS if k in task}


def private_task_view(task: dict) -> dict:
    """Grader-only slice of task.json."""
    return {k: task[k] for k in PRIVATE_TASK_KEYS if k in task}


def iter_payload_keys(obj: Any) -> Iterable[str]:
    """Yield every dict key found anywhere in a JSON-like payload."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from iter_payload_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_payload_keys(item)


def iter_payload_strings(obj: Any) -> Iterable[str]:
    """Yield every string value found anywhere in a JSON-like payload."""
    if isinstance(obj, dict):
        for value in obj.values():
            yield from iter_payload_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_payload_strings(item)
    elif isinstance(obj, str):
        yield obj


def find_leaked_keys(payload: Any) -> list[str]:
    """Return private labels found as keys or embedded in free text."""
    found = set(iter_payload_keys(payload)) & PRIVATE_KEY_NAMES
    text = "\n".join(iter_payload_strings(payload)).lower()
    found.update(name for name in PRIVATE_KEY_NAMES if name.lower() in text)
    return sorted(found)


def assert_no_leakage(payload: Any, *, where: str = "payload") -> None:
    leaked = find_leaked_keys(payload)
    if leaked:
        raise AssertionError(f"private keys leaked in {where}: {leaked}")
