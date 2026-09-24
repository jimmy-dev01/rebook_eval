"""Grader-only view of task.json (verifiers, reference, traps, hidden_info)."""
from __future__ import annotations

import json
from pathlib import Path

from rebook.paths import CLIENT
from rebook.privacy import private_task_view


def load_private_task(client_dir: Path | None = None) -> dict:
    root = client_dir or CLIENT
    task = json.loads((root / "task.json").read_text(encoding="utf-8"))
    return private_task_view(task)
