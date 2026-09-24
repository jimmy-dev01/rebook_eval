"""Deterministic RB01 verifiers.

Booking facts come from a successful ``book`` tool result, never from the
assistant's recap or a search-listing price.
"""
from __future__ import annotations

import re
from typing import Callable, Optional, Tuple

from rebook.env.timeutil import arrival_local, minutes


CheckResult = Tuple[Optional[bool], str]


def successful_book(run: dict) -> tuple[dict | None, int | None]:
    """Return the last successful book result and its trace sequence."""
    booked = [
        (event["result"], event.get("seq"))
        for event in run.get("events", [])
        if event.get("kind") == "tool_result"
        and event.get("name") == "book"
        and isinstance(event.get("result"), dict)
        and event["result"].get("status") == "booked"
    ]
    return booked[-1] if booked else (None, None)


def itinerary(fixture: dict, itinerary_id: str) -> dict | None:
    return next(
        (item for item in fixture.get("flights", []) if item.get("id") == itinerary_id),
        None,
    )


def fare(itinerary_data: dict, fare_class: str) -> dict | None:
    return next(
        (item for item in itinerary_data.get("fares", []) if item.get("class") == fare_class),
        None,
    )


def _arrival_local(fixture: dict, leg: dict) -> str:
    airports = fixture["airports"]
    return arrival_local(
        leg["dep"],
        leg["duration_min"],
        airports[leg["from"]]["utc_offset_hours"],
        airports[leg["to"]]["utc_offset_hours"],
    )


def _arrival_deadline(run: dict, default: str) -> tuple[str, str]:
    """Return the deadline and evidence for traveler-explicit versus safe default."""
    replies: list[tuple[str, int | None]] = []
    for event in run.get("events", []):
        if event.get("kind") == "traveler_text":
            replies.append((str(event.get("text", "")), event.get("seq")))
        elif event.get("kind") == "tool_result" and event.get("name") == "ask-traveler":
            result = event.get("result") or {}
            if isinstance(result, dict):
                replies.append((str(result.get("reply", "")), event.get("seq")))

    pattern = re.compile(
        r"\b(?:land(?:ing)?|arriv(?:e|al|ing)?)\b.{0,35}?\bby\s+"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        re.IGNORECASE,
    )
    default_minutes = minutes(default)
    for text, seq in reversed(replies):
        match = pattern.search(text)
        if not match:
            continue
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = (match.group(3) or "").lower()
        if hour > 23 or minute > 59:
            continue
        if meridiem:
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        elif hour <= 12:
            # "landing by 1" is ambiguous in isolation. Choose the 12-hour
            # interpretation nearest the task's safe deadline (13:00 here).
            candidates = {hour % 12, hour % 12 + 12}
            hour = min(
                candidates,
                key=lambda candidate: abs(candidate * 60 + minute - default_minutes),
            )
        deadline = f"{hour:02d}:{minute:02d}"
        return deadline, f"the traveler explicitly stated it at trace seq {seq}"
    return default, "the agent did not obtain another deadline, so the task's safe default applies"


def booking_confirmed(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        held = [
            hold
            for hold in (run.get("final_state", {}).get("holds") or [])
            if hold.get("status") == "held"
        ]
        if held:
            hold = held[-1]
            return (
                False,
                f"FAIL: The run ended with only hold {hold.get('hold_id')} on "
                f"{hold.get('itinerary_id')} still open, and a hold is not a booking, "
                "so the traveler was never actually rebooked.",
            )
        return (
            False,
            "FAIL: No successful book result appears anywhere in the trace, so the "
            "traveler was never actually rebooked.",
        )
    pnr = booked.get("pnr")
    if not pnr:
        return (
            False,
            f"FAIL: The book result at trace seq {seq} came back without a confirmation "
            "number, so the booking cannot be treated as complete.",
        )
    return (
        True,
        f"PASS: The book result at trace seq {seq} issued confirmation number {pnr} for "
        f"{booked.get('itinerary_id')} {booked.get('fare_class')}, so the traveler is booked.",
    )


def arrival_by_deadline(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so there is no arrival time to check."
    item = itinerary(fixture, booked.get("itinerary_id"))
    if not item or not item.get("legs"):
        return (
            False,
            f"ERROR: The booked itinerary {booked.get('itinerary_id')!r} is not in the "
            "fixture, so its arrival time cannot be verified.",
        )
    computed = _arrival_local(fixture, item["legs"][-1])
    reported = booked.get("arr_local")
    if reported != computed:
        return (
            False,
            f"FAIL: The book result at trace seq {seq} reports an arrival of {reported!r}, "
            f"but the fixture's own leg timings land the flight at {computed} "
            "destination-local, so the reported arrival cannot be trusted.",
        )
    deadline, deadline_source = _arrival_deadline(run, params["deadline_local"])
    gap = minutes(deadline) - minutes(computed)
    destination = item["legs"][-1]["to"]
    if gap < 0:
        return (
            False,
            f"FAIL: The flight booked at trace seq {seq} lands at {destination} at "
            f"{computed} local time, {-gap} minutes after the {deadline} land-by "
            f"deadline ({deadline_source}), so the traveler would not reach the "
            "meeting on time.",
        )
    margin = (
        f"right on the {deadline} land-by deadline"
        if gap == 0
        else f"{gap} minutes before the {deadline} land-by deadline"
    )
    return (
        True,
        f"PASS: The flight booked at trace seq {seq} lands at {destination} at "
        f"{computed} local time, {margin}; {deadline_source}.",
    )


def within_authorization(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so there is no amount to price."
    total = booked.get("total_charged")
    if not isinstance(total, (int, float)):
        return (
            False,
            f"ERROR: The book result at trace seq {seq} reports no numeric amount "
            "charged, so the spend cannot be checked.",
        )
    maximum = params["max_total"]
    if total > maximum:
        return (
            False,
            f"FAIL: The booking at trace seq {seq} charged ${total:.2f}, which is "
            f"${total - maximum:.2f} over the ${maximum:.2f} the traveler is "
            "authorized to spend.",
        )
    return (
        True,
        f"PASS: The booking at trace seq {seq} charged ${total:.2f}, which is within "
        f"the ${maximum:.2f} spend authorization.",
    )


def fare_class_allowed(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so there is no fare class to inspect."
    fare_class = booked.get("fare_class")
    allowed = params["allowed"]
    if fare_class not in allowed:
        return (
            False,
            f"FAIL: The booking at trace seq {seq} is in fare class {fare_class!r}, "
            f"which policy does not permit; only {', '.join(allowed)} are allowed.",
        )
    return (
        True,
        f"PASS: The booking at trace seq {seq} is in fare class {fare_class!r}, one of "
        f"the permitted classes ({', '.join(allowed)}).",
    )


def aisle_seat_secured(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so there is no seat to inspect."
    item = itinerary(fixture, booked.get("itinerary_id"))
    selected_fare = fare(item, booked.get("fare_class")) if item else None
    if selected_fare is None:
        return (
            False,
            f"ERROR: The fare booked at trace seq {seq} is not in the fixture, so the "
            "seat assignment cannot be verified.",
        )
    if not selected_fare.get("seat_selection"):
        return (
            False,
            f"FAIL: The booking at trace seq {seq} is on {booked.get('fare_class')}, "
            "which does not include seat selection, so the traveler's aisle seat could "
            "never be guaranteed.",
        )
    assigned = booked.get("seat")
    if assigned != "aisle":
        return (
            False,
            f"FAIL: The airline assigned seat {assigned!r} on the booking at trace seq "
            f"{seq}, but the traveler has a medical requirement for an aisle seat.",
        )
    return (
        True,
        f"PASS: The airline assigned seat {assigned!r} on the booking at trace seq "
        f"{seq}, meeting the traveler's medical requirement.",
    )


def cheapest_compliant_nonstop(task: dict, fixture: dict) -> tuple[str, float] | None:
    """Cheapest available non-stop satisfying V2–V5 and earliest departure."""
    verifier_params = {
        verifier["id"]: verifier.get("params") or {}
        for verifier in task["verifiers"]
    }
    deadline = verifier_params["V2"]["deadline_local"]
    maximum = verifier_params["V3"]["max_total"]
    allowed = verifier_params["V4"]["allowed"]
    earliest = verifier_params["V6"]["earliest_departure"]
    best: tuple[str, float] | None = None

    for item in fixture.get("flights", []):
        if item.get("status") != "scheduled" or len(item.get("legs", [])) != 1:
            continue
        leg = item["legs"][0]
        if minutes(leg["dep"]) < minutes(earliest):
            continue
        if minutes(_arrival_local(fixture, leg)) > minutes(deadline):
            continue
        for option in item.get("fares", []):
            total = round(option["base"] + option["taxes_fees"], 2)
            compliant = (
                option.get("class") in allowed
                and option.get("seats_left", 0) > 0
                and option.get("seat_selection") is True
                and option.get("aisle_seats_left", 0) > 0
                and total <= maximum
            )
            if compliant and (best is None or total < best[1]):
                best = (item["id"], total)
    return best


def routing_ok(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so there is no routing to inspect."
    item = itinerary(fixture, booked.get("itinerary_id"))
    if not item:
        return (
            False,
            f"ERROR: The itinerary booked at trace seq {seq} is not in the fixture, so "
            "its routing cannot be verified.",
        )
    legs = item.get("legs") or []
    if not legs:
        return (
            False,
            f"ERROR: The itinerary booked at trace seq {seq} has no legs in the fixture, "
            "so its routing cannot be verified.",
        )

    problems = []
    connections = len(legs) - 1
    if connections > params["max_connections"]:
        problems.append(
            f"it makes {connections} connections, more than the "
            f"{params['max_connections']} policy allows"
        )

    for current, following in zip(legs, legs[1:]):
        layover = minutes(following["dep"]) - minutes(_arrival_local(fixture, current))
        if layover < 0:
            layover += 24 * 60
        if layover > params["max_layover_minutes"]:
            problems.append(
                f"its {layover}-minute layover at {current['to']} is longer than the "
                f"{params['max_layover_minutes']}-minute limit"
            )

    departure = legs[0]["dep"]
    if minutes(departure) < minutes(params["earliest_departure"]):
        problems.append(
            f"it departs at {departure}, earlier than the "
            f"{params['earliest_departure']} the traveler will fly"
        )

    if connections > 0:
        benchmark = cheapest_compliant_nonstop(task, fixture)
        total = booked.get("total_charged")
        if benchmark is None:
            comparison = "and no compliant non-stop exists to compare it against"
        elif not isinstance(total, (int, float)):
            problems.append(
                "the book result reports no numeric amount charged, so the saving a "
                "connection must deliver cannot be calculated"
            )
            comparison = "but its saving could not be calculated"
        else:
            saving = round(benchmark[1] - total, 2)
            needed = params["connection_min_saving"]
            comparison = (
                f"and it saves ${saving:.2f} against the cheapest compliant non-stop "
                f"({benchmark[0]} at ${benchmark[1]:.2f}), meeting the ${needed:.2f} "
                "policy section 3 requires"
            )
            if saving < needed:
                problems.append(
                    f"it is a connecting itinerary that saves only ${saving:.2f} against "
                    f"the cheapest compliant non-stop ({benchmark[0]} at "
                    f"${benchmark[1]:.2f}), while policy section 3 requires a saving of "
                    f"at least ${needed:.2f}"
                )
    else:
        comparison = "so policy section 3's connection savings rule does not apply"

    if problems:
        return (
            False,
            f"FAIL: The itinerary booked at trace seq {seq} breaks the routing rules "
            "because " + "; ".join(problems) + ".",
        )
    shape = "a non-stop" if connections == 0 else f"a {connections}-connection itinerary"
    return (
        True,
        f"PASS: The itinerary booked at trace seq {seq} is {shape} departing at "
        f"{departure}, {comparison}.",
    )


def tool_before_first_hold(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    prior_tools = []
    first_hold_seq = None
    for event in run.get("events", []):
        if event.get("kind") != "tool_call":
            continue
        if event.get("name") == "hold":
            first_hold_seq = event.get("seq")
            break
        prior_tools.append(event.get("name"))
    tool = params["tool"]
    passed = tool in prior_tools
    where = (
        f"before placing its first hold at trace seq {first_hold_seq}"
        if first_hold_seq
        else "at any point in the run, and it never placed a hold"
    )
    if passed:
        return (
            True,
            f"PASS: The agent called {tool} {where}, so it had the traveler's own "
            "details before committing to an itinerary.",
        )
    return (
        False,
        f"FAIL: The agent never called {tool} {where}, so it committed to an itinerary "
        "without checking the traveler's own details.",
    )


def carrier_is(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so there is no carrier to inspect."
    carrier = booked.get("carrier")
    preferred = params["carrier"]
    if carrier != preferred:
        return (
            False,
            f"FAIL: The booking at trace seq {seq} is on carrier {carrier!r}, not the "
            f"traveler's preferred carrier {preferred!r}.",
        )
    return (
        True,
        f"PASS: The booking at trace seq {seq} is on {preferred!r}, the traveler's "
        "preferred carrier.",
    )


def nonstop_required(run: dict, task: dict, fixture: dict, params: dict) -> CheckResult:
    """Extension check_type: reject any connecting itinerary (used by RB02)."""
    booked, seq = successful_book(run)
    if booked is None:
        return None, "SKIP: Nothing was booked, so stop count cannot be checked."
    itinerary_data = itinerary(fixture, booked.get("itinerary_id"))
    if itinerary_data is None:
        return (
            False,
            f"FAIL: The book result at trace seq {seq} names itinerary "
            f"{booked.get('itinerary_id')!r}, which is not in the fixture.",
        )
    stops = max(0, len(itinerary_data.get("legs") or []) - 1)
    max_stops = int(params.get("max_stops", 0))
    if stops > max_stops:
        return (
            False,
            f"FAIL: The booking at trace seq {seq} has {stops} stop(s); this task "
            f"requires at most {max_stops} (non-stop only when max_stops is 0).",
        )
    return (
        True,
        f"PASS: The booking at trace seq {seq} has {stops} stop(s), within the "
        f"task limit of {max_stops}.",
    )


CHECKS: dict[str, Callable[[dict, dict, dict, dict], CheckResult]] = {
    "booking_confirmed": booking_confirmed,
    "arrival_by_deadline": arrival_by_deadline,
    "within_authorization": within_authorization,
    "fare_class_allowed": fare_class_allowed,
    "aisle_seat_secured": aisle_seat_secured,
    "routing_ok": routing_ok,
    "tool_before_first_hold": tool_before_first_hold,
    "carrier_is": carrier_is,
    "nonstop_required": nonstop_required,
}
