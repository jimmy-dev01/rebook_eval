"""Agents that drive the environment: scripted ones of known quality, and adversarial ones."""
from rebook.agents.adversarial import (
    ADVERSARIAL_AGENTS,
    hold_and_claim,
    ignore_deadline,
    quote_base,
    run_all_adversaries,
)
from rebook.agents.run_builder import session_to_run

__all__ = [
    "ADVERSARIAL_AGENTS",
    "hold_and_claim",
    "ignore_deadline",
    "quote_base",
    "run_all_adversaries",
    "session_to_run",
]
