"""Build a gradeable run dict from a live Session."""
from __future__ import annotations

from rebook.env.session import Session


def session_to_run(
    session: Session,
    *,
    run_id: str,
    final_output: str,
    model: str = "scripted-adversary",
) -> dict:
    """Freeze one episode into the same shape as shipped runs/R0x.json."""
    return {
        "run_id": run_id,
        "task_id": session.public_task.get("task_id", "RB01"),
        "snapshot_id": session.world.snapshot_id,
        "model": model,
        "stop_reason": "booked" if session.booking else "hold_only",
        "events": list(session.events),
        "final_output": final_output,
        "final_state": session.final_state(),
    }
