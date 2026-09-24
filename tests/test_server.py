"""HTTP boundary contract: proves the transport adds no new leak path.

Runs the evaluator server in-process on an ephemeral port (no Docker
required for this test); the Docker files just put this same server behind
a real container/network fence for a live agent.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from rebook.privacy import find_leaked_keys
from rebook.server import serve


@pytest.fixture()
def base_url():
    httpd = serve("127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def _post(url: str, path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url + path, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(url: str, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(url + path, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_healthz(base_url):
    status, body = _get(base_url, "/healthz")
    assert status == 200
    assert body == {"ok": True}


def test_reset_gives_session_and_clean_observation(base_url):
    status, body = _post(base_url, "/reset", {})
    assert status == 200
    assert body["session_id"]
    assert body["observation"]["user_message"]
    assert find_leaked_keys(body["observation"]) == []


def test_step_unknown_session_is_404_not_a_crash(base_url):
    status, body = _post(base_url, "/step", {"session_id": "nope", "action": {}})
    assert status == 404
    assert "error" in body


def test_full_booking_round_trip_over_http_stays_leak_free(base_url):
    _, reset_body = _post(base_url, "/reset", {})
    sid = reset_body["session_id"]

    _, profile = _post(
        base_url, "/step", {"session_id": sid, "action": {"name": "get-traveler-profile", "args": {}}}
    )
    assert find_leaked_keys(profile["result"]) == []

    _, held = _post(
        base_url,
        "/step",
        {
            "session_id": sid,
            "action": {
                "name": "hold",
                "args": {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"},
            },
        },
    )
    hold_id = held["result"]["hold_id"]
    assert find_leaked_keys(held["result"]) == []

    _, booked = _post(
        base_url, "/step", {"session_id": sid, "action": {"name": "book", "args": {"hold_id": hold_id}}}
    )
    assert booked["result"]["status"] == "booked"
    assert booked["result"]["itinerary_id"] == "FL0925"
    assert find_leaked_keys(booked["result"]) == []


def test_malformed_request_error_never_echoes_internals(base_url):
    status, body = _post(base_url, "/step", {"session_id": "x", "action": {"name": 12345}})
    assert status in (400, 404)
    # The error is a type name only, never a repr of internal state.
    assert find_leaked_keys(body) == []


def test_sessions_are_isolated_from_each_other(base_url):
    _, first = _post(base_url, "/reset", {})
    _, second = _post(base_url, "/reset", {})
    assert first["session_id"] != second["session_id"]
    # FL0925 premium starts with 2 aisle seats in the fixture; hold one in
    # the first session only.
    _post(
        base_url,
        "/step",
        {
            "session_id": first["session_id"],
            "action": {
                "name": "hold",
                "args": {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"},
            },
        },
    )
    # Second session's own fare inventory is untouched by the first's hold.
    _, fares = _post(
        base_url,
        "/step",
        {"session_id": second["session_id"], "action": {"name": "get-fares", "args": {"itinerary_id": "FL0925"}}},
    )
    premium_fare = next(f for f in fares["result"]["fares"] if f["class"] == "premium")
    assert premium_fare["aisle_seats_left"] == 2
