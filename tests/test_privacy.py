"""Step 3: public vs private boundary — tools never see grading secrets."""
from __future__ import annotations

import json

from rebook.env import Session, reset
from rebook.env.world import World
from rebook.grader import load_private_task
from rebook.paths import CLIENT
from rebook.privacy import (
    PRIVATE_TASK_KEYS,
    find_leaked_keys,
    private_task_view,
    public_task_view,
)


def test_public_task_excludes_grading_secrets():
    task = json.loads((CLIENT / "task.json").read_text(encoding="utf-8"))
    pub = public_task_view(task)
    assert "user_message" in pub
    assert "scripted_replies" in pub
    for key in PRIVATE_TASK_KEYS:
        assert key not in pub, key


def test_private_task_has_verifiers_and_reference():
    priv = load_private_task()
    assert "verifiers" in priv
    assert "reference_booking" in priv
    assert "hidden_info" in priv
    assert "traps" in priv
    assert "user_message" not in priv


def test_session_observation_has_no_private_keys():
    session = reset()
    obs = session.observation()
    assert obs["user_message"]
    assert find_leaked_keys(obs) == []
    for key in PRIVATE_TASK_KEYS:
        assert key not in obs


def test_all_tools_return_no_private_keys():
    """Exercise every tool once and assert payloads are clean."""
    session = reset()
    actions = [
        {"name": "get-traveler-profile", "args": {}},
        {"name": "get-policy", "args": {}},
        {"name": "search-flights", "args": {"origin": "DEN", "destination": "ORD"}},
        {"name": "get-fares", "args": {"itinerary_id": "FL0925"}},
        {"name": "hold", "args": {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"}},
    ]
    for action in actions:
        result = session.step(action)
        assert find_leaked_keys(result) == [], (action["name"], find_leaked_keys(result))

    hold_id = next(h["hold_id"] for h in session.holds.values() if h["status"] == "held")
    # cancel path
    session2 = reset()
    session2.step({"name": "hold", "args": {"itinerary_id": "FL0925", "fare_class": "main", "seat_pref": "aisle"}})
    hid = next(h["hold_id"] for h in session2.holds.values())
    cancel = session2.step({"name": "cancel-hold", "args": {"hold_id": hid}})
    assert find_leaked_keys(cancel) == []

    book = session.step({"name": "book", "args": {"hold_id": hold_id}})
    assert book.get("status") == "booked"
    assert find_leaked_keys(book) == []

    session3 = reset()
    ask = session3.step({"name": "ask-traveler", "args": {"question": "What time do I need to land for downtown?"}})
    assert "reply" in ask
    assert find_leaked_keys(ask) == []


def test_private_values_are_private_by_default_when_task_shape_changes():
    """New private fields cannot leak because Session receives only the public slice."""
    task = json.loads((CLIENT / "task.json").read_text(encoding="utf-8"))
    sentinels = []
    for index, key in enumerate(PRIVATE_TASK_KEYS):
        sentinel = f"PRIVATE-SENTINEL-{index}-{key}"
        task[key] = {"new_nested_field": [sentinel]}
        sentinels.append(sentinel)

    fixture = json.loads((CLIENT / "fixture.json").read_text(encoding="utf-8"))
    policy = (CLIENT / "policy.md").read_text(encoding="utf-8")
    session = Session(World(fixture, policy), public_task_view(task))
    payloads = [
        session.observation(),
        session.step({"name": "get-traveler-profile", "args": {}}),
        session.step({"name": "get-policy", "args": {}}),
        session.step(
            {
                "name": "search-flights",
                "args": {"origin": "DEN", "destination": "ORD"},
            }
        ),
        session.step({"name": "get-fares", "args": {"itinerary_id": "FL0925"}}),
    ]
    serialized = json.dumps(payloads, sort_keys=True)
    assert all(sentinel not in serialized for sentinel in sentinels)


def test_private_labels_embedded_in_free_text_are_detected():
    assert find_leaked_keys({"message": "do not expose reference_booking"}) == [
        "reference_booking"
    ]


def test_private_view_not_reachable_via_session_attributes_for_tools():
    """Session keeps only the public task slice."""
    session = reset()
    assert set(session.public_task).isdisjoint(PRIVATE_TASK_KEYS)
    # Full task on disk still has secrets — grader loads them separately.
    raw = json.loads((CLIENT / "task.json").read_text(encoding="utf-8"))
    assert private_task_view(raw)["reference_booking"]
