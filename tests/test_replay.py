"""Step 4 done-when: replaying R01–R06 matches recorded final state and tool results."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from rebook.env.replay import replay_all, replay_and_check
from rebook.paths import CLIENT, ROOT

RUN_IDS = ["R01", "R02", "R03", "R04", "R05", "R06"]


@pytest.mark.parametrize("run_id", RUN_IDS)
def test_replay_matches_shipped_run(run_id):
    run = json.loads((CLIENT / "runs" / f"{run_id}.json").read_text(encoding="utf-8"))
    result = replay_and_check(run)
    assert result["ok"], (
        f"{run_id} replay failed\n"
        f"state: {result['state_diffs']}\n"
        f"tool: {result['tool_diffs'][:3]}"
    )


def test_replay_all_six():
    results = replay_all()
    assert len(results) == 6
    assert all(r["ok"] for r in results)


def test_trace_state_and_reward_are_byte_identical_across_processes():
    """Hash randomization cannot change ordering, IDs, state, or reward."""
    program = """
import json
from rebook.env import reset
from rebook.grader import grade_run
from rebook.paths import CLIENT

session = reset()
actions = [
    {"name": "get-traveler-profile", "args": {}},
    {"name": "get-policy", "args": {}},
    {"name": "search-flights", "args": {"origin": "DEN", "destination": "ORD"}},
    {"name": "get-fares", "args": {"itinerary_id": "FL0925"}},
    {"name": "hold", "args": {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"}},
    {"name": "book", "args": {"hold_id": "H1"}},
]
for action in actions:
    session.step(action)
run = {
    "run_id": "cross-process",
    "task_id": "RB01",
    "snapshot_id": session.world.snapshot_id,
    "events": session.events,
    "final_output": "Booked FL 925, arriving 12:55 PM, for $550.10.",
    "final_state": session.final_state(),
}
task = json.loads((CLIENT / "task.json").read_text())
fixture = json.loads((CLIENT / "fixture.json").read_text())
grade = grade_run(run, task, fixture)
print(json.dumps({"run": run, "grade": grade}, separators=(",", ":")))
"""
    outputs = []
    for seed in ("1", "8675309"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", program],
                cwd=ROOT,
                env=env,
            )
        )
    assert outputs[0] == outputs[1]
