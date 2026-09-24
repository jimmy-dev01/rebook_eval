"""Basic environment behaviour for the eight tools."""
from __future__ import annotations

from rebook.env import reset
from rebook.env.timeutil import arrival_local


def test_ord_arrival_accounts_for_timezone():
    # DEN −6, ORD −5: 09:25 + 150 min → 12:55 ORD, not 11:55.
    assert arrival_local("09:25", 150, -6, -5) == "12:55"


def test_hold_cancel_restores_aisle_inventory():
    session = reset()
    before = session.world.fare("FL0925", "premium")["aisle_seats_left"]
    session.step({"name": "hold", "args": {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"}})
    mid = session.world.fare("FL0925", "premium")["aisle_seats_left"]
    assert mid == before - 1
    hid = next(h["hold_id"] for h in session.holds.values())
    session.step({"name": "cancel-hold", "args": {"hold_id": hid}})
    assert session.world.fare("FL0925", "premium")["aisle_seats_left"] == before


def test_book_keeps_aisle_inventory_taken():
    """A booked seat is consumed; book must not restore the hold's decrement."""
    session = reset()
    fare = session.world.fare("FL0925", "premium")
    aisle_before = fare["aisle_seats_left"]
    seats_before = fare["seats_left"]
    hold = session.step(
        {
            "name": "hold",
            "args": {
                "itinerary_id": "FL0925",
                "fare_class": "premium",
                "seat_pref": "aisle",
            },
        }
    )
    after_hold = session.world.fare("FL0925", "premium")
    assert after_hold["aisle_seats_left"] == aisle_before - 1
    assert after_hold["seats_left"] == seats_before - 1
    book = session.step({"name": "book", "args": {"hold_id": hold["hold_id"]}})
    assert book["status"] == "booked"
    after_book = session.world.fare("FL0925", "premium")
    assert after_book["aisle_seats_left"] == aisle_before - 1
    assert after_book["seats_left"] == seats_before - 1


def test_hold_assigns_window_when_no_aisle():
    session = reset()
    result = session.step(
        {"name": "hold", "args": {"itinerary_id": "FL0925", "fare_class": "main", "seat_pref": "aisle"}}
    )
    assert result["seat"] == "window"
    assert "no aisle" in result.get("note", "").lower()


def test_book_reference_itinerary():
    session = reset()
    session.step(
        {"name": "hold", "args": {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"}}
    )
    hid = next(h["hold_id"] for h in session.holds.values())
    book = session.step({"name": "book", "args": {"hold_id": hid}})
    assert book["status"] == "booked"
    assert book["itinerary_id"] == "FL0925"
    assert book["fare_class"] == "premium"
    assert book["seat"] == "aisle"
    assert book["total_charged"] == 550.1
    assert book["arr_local"] == "12:55"
    assert session.final_state()["booking"]["pnr"] == book["pnr"]


def test_ask_traveler_limit():
    session = reset()
    r1 = session.step({"name": "ask-traveler", "args": {"question": "When should I land downtown?"}})
    assert r1["clarifications_remaining"] == 1
    r2 = session.step({"name": "ask-traveler", "args": {"question": "aisle seat?"}})
    assert r2["clarifications_remaining"] == 0
    r3 = session.step({"name": "ask-traveler", "args": {"question": "one more?"}})
    assert "error" in r3