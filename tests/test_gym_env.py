"""Contract for the optional Gymnasium adapter (rebook.env.gym_env).

Skipped entirely if gymnasium isn't installed, so `make test` (the base
suite) never depends on it. Run `make setup-gym` first, then
`.venv/bin/python -m pytest tests/test_gym_env.py` to exercise these.
"""
from __future__ import annotations

import json
import os

import pytest

if os.getenv("REBOOK_TEST_GYM") != "1":
    pytest.skip(
        "optional Gymnasium tests run only through `make test-gym`",
        allow_module_level=True,
    )

gym = pytest.importorskip("gymnasium", exc_type=ImportError)

from rebook.env.gym_env import RebookGymEnv  # noqa: E402


def make_env():
    return RebookGymEnv(max_steps=10)


def test_reset_returns_observation_and_info():
    env = make_env()
    obs, info = env.reset()
    assert obs["done"] == 0
    assert "observation" in info
    assert info["observation"]["task_id"]


def test_step_is_gymnasium_five_tuple_and_matches_spaces():
    env = make_env()
    env.reset()
    action = {"tool": "get-traveler-profile", "args_json": "{}"}
    assert env.action_space.contains(action)
    obs, reward, terminated, truncated, info = env.step(action)
    assert env.observation_space.contains(obs)
    assert reward == 0.0
    assert terminated is False
    assert truncated is False
    profile = json.loads(obs["result_json"])
    assert profile.get("seat_preference") == "aisle"


def test_booking_the_reference_itinerary_terminates_with_full_reward():
    env = make_env()
    env.reset()
    # V8 requires get-traveler-profile before the first hold, same as R01.
    env.step({"tool": "get-traveler-profile", "args_json": "{}"})
    hold_obs, *_ = env.step({"tool": "hold", "args_json": json.dumps(
        {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"}
    )})
    hold_id = json.loads(hold_obs["result_json"])["hold_id"]
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "book", "args_json": json.dumps({"hold_id": hold_id})}
    )
    assert terminated is True
    assert truncated is False
    assert reward == 1.0
    assert info["grade"]["result"] == "PASS"
    assert obs["done"] == 1


def test_unknown_tool_is_an_observation_not_a_crash():
    env = make_env()
    env.reset()
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "not-a-real-tool", "args_json": "{}"}
    )
    assert "error" in json.loads(obs["result_json"])
    assert terminated is False


def test_finish_action_ends_episode_and_grades_final_output():
    env = make_env()
    env.reset()
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "finish", "args_json": json.dumps({"message": "Sorry, I could not rebook you."})}
    )
    assert terminated is True
    assert info["run"]["final_output"] == "Sorry, I could not rebook you."
    # No booking happened, so V1 fails and score is 0.
    assert reward == 0.0
    assert info["grade"]["result"] == "FAIL"


def test_max_steps_truncates_with_partial_grade_as_reward():
    """A cut-off episode is graded exactly like a real unfinished run: V1
    (no booking) fails, but V8 (profile fetched before any hold) still
    passes, so reward is that partial score, not a flat zero."""
    env = RebookGymEnv(max_steps=2)
    env.reset()
    env.step({"tool": "get-traveler-profile", "args_json": "{}"})
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "get-policy", "args_json": "{}"}
    )
    assert truncated is True
    assert terminated is False
    assert info["grade"]["result"] == "FAIL"
    assert 0.0 < reward < 1.0
