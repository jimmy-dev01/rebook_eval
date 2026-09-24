"""Optional Gymnasium adapter over :class:`rebook.env.session.Session`.

Why this exists
----------------
The environment loop (``Session.reset`` / ``Session.step``) is the source of
truth and has no Gymnasium dependency — the core setup, tests, and grader
never import this module. This adapter exists only so a future RL training
loop (policy-gradient fine-tuning, a `VecEnv`, curriculum sampling, etc.) can
drive the same fixture through the standard ``gymnasium.Env`` interface
without any change to ``Session``, the tools, or the grader.

Design choice: tool calls and results are variable-shaped JSON (a `hold`
result looks nothing like a `search-flights` result), which does not map
cleanly onto Gymnasium's typed numeric/box spaces. Rather than force a fixed
schema (and silently drop fields a future verifier might need), this adapter
represents one *action* as a JSON-encoded tool call and one *observation* as
the JSON-encoded tool result, using ``gymnasium.spaces.Text``. A trainer that
wants structured fields parses the JSON on its side; nothing here is hidden
or lossy.

Reward: 0.0 on every non-terminal step. On the step that ends the episode,
reward is the same deterministic score ``rebook.grader.engine.grade_run``
would give a finished run (V7 excluded here — no live judge client in a
training loop). This is the only reward signal; nothing here re-derives
policy checks independently of the grader, so training and evaluation can
never disagree about what "good" means.

An episode ends when:
- the agent's ``book`` call succeeds (a PNR is issued), or
- the agent calls the synthetic ``finish`` action with a closing message
  (mirrors ``final_output`` in the shipped runs), or
- ``max_steps`` tool calls have happened without either of the above
  (``truncated=True``). The reward is still whatever `grade_run` gives the
  partial trace — e.g. V1 (a booking exists) fails, but a verifier like V8
  (profile fetched before the first hold) can still pass, the same way it
  would if a real run were cut off mid-conversation.

Not a dependency of anything else in this package; install with
``make setup-gym`` and see ``tests/test_gym_env.py`` for the contract this
file is expected to hold.
"""
from __future__ import annotations

import json
import string
from typing import Any, Optional

import gymnasium as gym
from gymnasium import spaces

# Tool names use hyphens; JSON args/results use quotes, braces, colons, etc.
# Gymnasium's default Text charset is alphanumeric only, so widen it to
# printable ASCII rather than silently rejecting valid JSON payloads.
_JSON_CHARSET = string.printable

from rebook.env.session import TOOL_NAMES, Session
from rebook.grader.engine import grade_run
from rebook.paths import CLIENT

MAX_TEXT = 8000


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class RebookGymEnv(gym.Env):
    """`reset()` / `step()` over the RB01 fixture, one action = one tool call."""

    metadata = {"render_modes": []}

    def __init__(self, *, client_dir=None, max_steps: int = 40):
        super().__init__()
        self.client_dir = client_dir or CLIENT
        self.max_steps = max_steps
        self.task = _load(self.client_dir / "task.json")
        self.fixture = _load(self.client_dir / "fixture.json")
        self.action_space = spaces.Dict(
            {
                # "finish" is synthetic: it is not one of the eight airline
                # tools, it is how the agent submits its closing message and
                # ends the episode, same role as `final_output` in a shipped run.
                "tool": spaces.Text(max_length=32, charset=_JSON_CHARSET),
                "args_json": spaces.Text(max_length=MAX_TEXT, charset=_JSON_CHARSET),
            }
        )
        self.observation_space = spaces.Dict(
            {
                "result_json": spaces.Text(max_length=MAX_TEXT, charset=_JSON_CHARSET),
                "done": spaces.Discrete(2),
            }
        )
        self._session: Optional[Session] = None
        self._steps = 0
        self._final_output = ""

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self._session = Session.reset(self.client_dir)
        self._steps = 0
        self._final_output = ""
        obs = self._observation()
        info = {"observation": self._session.observation()}
        return obs, info

    def step(self, action: dict):
        if self._session is None:
            raise RuntimeError("call reset() before step()")
        tool = action.get("tool")
        args = json.loads(action.get("args_json") or "{}")
        self._steps += 1

        if tool == "finish":
            self._final_output = str(args.get("message", ""))
            self._session.step({"text": self._final_output})
            return self._finish(truncated=False)

        if tool not in TOOL_NAMES:
            result = {"error": f"unknown tool {tool!r}; expected one of {TOOL_NAMES} or 'finish'"}
        else:
            result = self._session.step({"name": tool, "args": args})

        booked = tool == "book" and isinstance(result, dict) and result.get("status") == "booked"
        if booked:
            return self._finish(truncated=False)

        if self._steps >= self.max_steps:
            return self._finish(truncated=True, last_result=result)

        obs = self._observation(result)
        return obs, 0.0, False, False, {"result": result}

    def _finish(self, *, truncated: bool, last_result: Any = None):
        run = self._to_run()
        grade = grade_run(run, self.task, self.fixture)
        reward = grade["score"] or 0.0
        obs = self._observation(last_result, done=True)
        info = {"grade": grade, "run": run}
        return obs, reward, not truncated, truncated, info

    def _observation(self, result: Any = None, *, done: bool = False) -> dict:
        return {
            "result_json": json.dumps(result if result is not None else {}, default=str),
            "done": 1 if done else 0,
        }

    def _to_run(self) -> dict:
        assert self._session is not None
        return {
            "run_id": "gym-episode",
            "snapshot_id": self._session.world.snapshot_id,
            "task_id": self.task.get("task_id"),
            "events": self._session.events,
            "final_state": self._session.final_state(),
            "final_output": self._final_output,
        }

    def render(self):  # pragma: no cover - no visual rendering
        return None
