"""Confirms the flaws in the client's grader (naive_grader.py).

Each test works out what really happened in a run, from the fixture and the airline tools' own results,
then shows the old grader getting it wrong. The runs are the six shipped ones, or copies of R01 (a correct
run) with one thing changed. A passing test means the flaw is confirmed; the old grader is frozen, so
these should always pass.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from rebook.baseline import load_naive_grader
from rebook.paths import CLIENT

naive = load_naive_grader()
TASK = json.loads((CLIENT / "task.json").read_text(encoding="utf-8"))
FIXTURE = json.loads((CLIENT / "fixture.json").read_text(encoding="utf-8"))
PARAMS = {v["id"]: v.get("params") or {} for v in TASK["verifiers"]}
DEADLINE = PARAMS["V2"]["deadline_local"]  # 13:00, the 14:00 meeting less 60 minutes to downtown


def load_run(run_id):
    return json.loads((CLIENT / "runs" / f"{run_id}.json").read_text(encoding="utf-8"))


def tool_results(run, name):
    return [e["result"] for e in run["events"] if e["kind"] == "tool_result" and e["name"] == name]


def book_result(run):
    """The run's one successful `book` result."""
    [book] = [r for r in tool_results(run, "book") if r.get("status") == "booked"]
    return book


def old_verdict(grade, vid):
    """The (pass, evidence) pair the old grader gave one verifier."""
    v = next(v for v in grade["verifiers"] if v["id"] == vid)
    return v["pass"], v["evidence"]


# ---- facts, worked out from the fixture ------------------------------------------------------

def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def itinerary(iid):
    return next(it for it in FIXTURE["flights"] if it["id"] == iid)


def fare(iid, fare_class):
    return next(f for f in itinerary(iid)["fares"] if f["class"] == fare_class)


def total(f):
    return round(f["base"] + f["taxes_fees"], 2)


def arrival(leg):
    """Local arrival time: departure, plus flight time, plus the time-zone difference."""
    airports = FIXTURE["airports"]
    shift = airports[leg["to"]]["utc_offset_hours"] - airports[leg["from"]]["utc_offset_hours"]
    m = minutes(leg["dep"]) + leg["duration_min"] + shift * 60
    return f"{m // 60:02d}:{m % 60:02d}"


def cheapest_compliant_nonstop():
    """(total, itinerary, fare class) of the cheapest non-stop that meets every other rule: policy §3's yardstick."""
    options = []
    for it in FIXTURE["flights"]:
        if it["status"] != "scheduled" or len(it["legs"]) != 1:
            continue
        leg = it["legs"][0]
        if minutes(leg["dep"]) < minutes(PARAMS["V6"]["earliest_departure"]) or minutes(arrival(leg)) > minutes(DEADLINE):
            continue
        for f in it["fares"]:
            if (f["class"] in PARAMS["V4"]["allowed"] and f["seat_selection"] and f["aisle_seats_left"] > 0
                    and f["seats_left"] > 0 and total(f) <= PARAMS["V3"]["max_total"]):
                options.append((total(f), it["id"], f["class"]))
    return min(options)


# ---- runs built from R01 with one thing changed ------------------------------------------------

def events_before_first_hold(run):
    first = next(i for i, e in enumerate(run["events"]) if e["kind"] == "tool_call" and e["name"] == "hold")
    return copy.deepcopy(run["events"][:first])


def run_from_r01(itinerary_id, fare_class, recap, book=True):
    """R01's real profile, policy, search and fares calls, then an aisle hold on the given fare and, if book, a booking.

    The hold and booking results are filled in from the fixture the way the recorded runs show the airline
    doing it: the total is base plus taxes and fees, and an aisle request gets an aisle if one is left,
    a window if not, and no seat at all on a fare without seat selection.
    """
    r01 = load_run("R01")
    events = events_before_first_hold(r01)
    f = fare(itinerary_id, fare_class)
    seat = ("aisle" if f["aisle_seats_left"] > 0 else "window") if f["seat_selection"] else None
    hold = {"hold_id": "H1", "itinerary_id": itinerary_id, "fare_class": fare_class, "seat": seat, "base": f["base"],
            "taxes_fees": f["taxes_fees"], "total": total(f), "expires_in_minutes": 30, "status": "held"}
    calls = [("hold", {"itinerary_id": itinerary_id, "fare_class": fare_class, "seat_pref": "aisle"}, hold)]
    booking = None
    if book:
        listing = next(i for i in tool_results(r01, "search-flights")[0]["itineraries"] if i["itinerary_id"] == itinerary_id)
        booking = {"pnr": "RTEST1", "itinerary_id": itinerary_id, "carrier": listing["carrier"], "fare_class": fare_class,
                   "seat": seat, "total_charged": total(f), "legs": listing["legs"], "arr_local": listing["legs"][-1]["arr_local"]}
        calls.append(("book", {"hold_id": "H1"}, {"status": "booked", **booking}))
    for name, args, result in calls:
        events.append({"seq": events[-1]["seq"] + 1, "kind": "tool_call", "name": name, "args": args})
        events.append({"seq": events[-1]["seq"] + 1, "kind": "tool_result", "name": name, "result": result})
    kept = {k: hold[k] for k in ("hold_id", "itinerary_id", "fare_class", "seat", "total")}
    return {"run_id": f"R01 with {itinerary_id} {fare_class}", "task_id": TASK["task_id"], "snapshot_id": r01["snapshot_id"],
            "events": events, "final_output": recap,
            "final_state": {"booking": booking, "holds": [{**kept, "status": "booked" if book else "held"}], "clarifications": 0}}


def test_built_runs_match_what_the_real_airline_returned():
    """Sanity check on the hand-built runs: for fares the recorded runs really used, the built hold and
    booking results match the real ones, apart from ids and notes."""
    def strip(result, *keys):
        return {k: v for k, v in result.items() if k not in keys}

    for iid, fare_class, run_id, index in [("FL0925", "premium", "R01", 0), ("FL0925", "main", "R06", 0),
                                           ("MR1105", "main", "R03", 1), ("SW0650-MSP", "main", "R04", 0)]:
        built = tool_results(run_from_r01(iid, fare_class, recap=""), "hold")[0]
        real = tool_results(load_run(run_id), "hold")[index]
        assert strip(built, "hold_id") == strip(real, "hold_id", "note")
    for run_id in ("R01", "R03", "R04"):
        real = book_result(load_run(run_id))
        built = book_result(run_from_r01(real["itinerary_id"], real["fare_class"], recap=""))
        assert strip(built, "pnr") == strip(real, "pnr")


# ---- wrong verdicts on the shipped runs ---------------------------------------------------------

@pytest.mark.parametrize("run_id", ["R02", "R06"])
def test_arrival_check_passes_a_1345_landing(run_id):
    """FL1015 lands at 13:45 Chicago time, 45 minutes after the deadline. The old grader adds the flight
    time to the Denver clock (12:45) and compares that with the 14:00 meeting instead of the deadline."""
    run = load_run(run_id)
    book = book_result(run)
    assert book["itinerary_id"] == "FL1015"
    assert book["arr_local"] == arrival(itinerary("FL1015")["legs"][-1]) == "13:45"
    assert minutes(book["arr_local"]) > minutes(DEADLINE)
    grade = naive.grade(run, TASK, FIXTURE)
    passed, evidence = old_verdict(grade, "V2")
    assert passed and "= 12:45 vs meeting 14:00" in evidence
    assert grade["result"] == "PASS"


def test_arrival_check_passes_r03_which_lands_after_the_meeting_starts():
    """MR1105 lands at 14:30, after the meeting has started. The traveler said "landing by 1 at the latest"
    twice, and the agent's own recap admits she'll be late. The old grader works out 13:30."""
    run = load_run("R03")
    book = book_result(run)
    assert book["arr_local"] == arrival(itinerary("MR1105")["legs"][-1]) == "14:30"
    replies = [r["reply"] for r in tool_results(run, "ask-traveler")]
    assert len(replies) == 2 and all("landing by 1 at the latest" in r for r in replies)
    assert "30 minutes after your meeting start" in run["final_output"]
    grade = naive.grade(run, TASK, FIXTURE)
    passed, evidence = old_verdict(grade, "V2")
    assert passed and "= 13:30 vs meeting 14:00" in evidence
    assert grade["result"] == "PASS"


def test_routing_check_passes_r04_which_breaks_policy_3():
    """SW0650-MSP connects through Minneapolis for $438.00. Policy §3 allows a connection only if it's at
    least $120 cheaper than the cheapest compliant non-stop, FL0925 Premium at $550.10. It saves $112.10.
    The old grader only counts stops."""
    run = load_run("R04")
    book = book_result(run)
    nonstop_total, nonstop, nonstop_class = cheapest_compliant_nonstop()
    assert (nonstop_total, nonstop, nonstop_class) == (550.1, "FL0925", "premium")
    saving = round(nonstop_total - book["total_charged"], 2)
    assert book["itinerary_id"] == "SW0650-MSP" and saving == 112.1
    assert saving < PARAMS["V6"]["connection_min_saving"]
    grade = naive.grade(run, TASK, FIXTURE)
    assert old_verdict(grade, "V6") == (True, "SW0650-MSP has 1 connection(s)")
    assert grade["result"] == "PASS"


# ---- right verdicts, wrong evidence --------------------------------------------------------------

@pytest.mark.parametrize("run_id", ["R01", "R05"])
def test_price_check_quotes_the_basic_base_fare_not_the_amount_charged(run_id):
    """Both runs were charged $550.10 for FL0925 Premium, but the old grader's evidence quotes $214.0, the
    Basic base fare from the search listing. The verdict is right, but for the wrong reason."""
    run = load_run(run_id)
    book = book_result(run)
    assert (book["fare_class"], book["total_charged"]) == ("premium", 550.1)
    assert fare("FL0925", "basic")["base"] == 214.0
    assert old_verdict(naive.grade(run, TASK, FIXTURE), "V3") == (True, "FL0925 fare $214.0 vs max $650.0")


@pytest.mark.parametrize("run_id", ["R03", "R06"])
def test_seat_check_cites_a_hold_that_got_a_window_seat(run_id):
    """The old grader's seat evidence points at the first hold, on FL0925 Main. The airline gave that hold a
    window seat and the agent cancelled it; the booking is on another flight."""
    run = load_run(run_id)
    first_hold = tool_results(run, "hold")[0]
    assert (first_hold["itinerary_id"], first_hold["seat"]) == ("FL0925", "window")
    assert book_result(run)["itinerary_id"] != "FL0925"
    assert old_verdict(naive.grade(run, TASK, FIXTURE), "V5") == (True, "hold requested seat_pref=aisle on FL0925")


# ---- broken runs the old grader passes -----------------------------------------------------------

def test_hold_that_was_never_booked_gets_a_perfect_score():
    """The agent holds FL0925 Premium, never calls book, and tells the traveler she's booked. Policy §6 says
    a hold is not a booking. The old grader counts the hold and gives a perfect score."""
    run = run_from_r01("FL0925", "premium", book=False,
                       recap="You're booked on Frontline FL 925 tomorrow, landing 12:55pm, aisle seat, $550.10 total.")
    assert not tool_results(run, "book") and run["final_state"]["booking"] is None
    grade = naive.grade(run, TASK, FIXTURE)
    assert old_verdict(grade, "V1") == (True, "seat secured: hold H1 on FL0925")
    assert (grade["result"], grade["score"]) == ("PASS", 1.0)


def test_recap_saying_confirmed_counts_as_a_booking():
    """No hold and no booking at all, only a recap that says "confirmed". The old grader's booking check
    passes it on the wording alone."""
    r01 = load_run("R01")
    run = {**r01, "events": events_before_first_hold(r01),
           "final_output": "Your booking is confirmed: Frontline FL 925, landing 12:55pm.",
           "final_state": {"booking": None, "holds": [], "clarifications": 0}}
    assert not tool_results(run, "hold") and not tool_results(run, "book")
    assert old_verdict(naive.grade(run, TASK, FIXTURE), "V1") == (True, "recap confirms the booking")


def test_price_check_passes_a_booking_over_the_650_limit():
    """SW0700 Premium is charged $683.40, over the $650.00 limit (policy §2). The old grader checks the
    search listing's lowest base fare, $203.0 for Basic, and passes the whole run."""
    run = run_from_r01("SW0700", "premium", recap="Booked Skyway SW 700 Premium with an aisle seat. The fare is $612, inside policy.")
    assert book_result(run)["total_charged"] == 683.4 > PARAMS["V3"]["max_total"]
    grade = naive.grade(run, TASK, FIXTURE)
    assert old_verdict(grade, "V3") == (True, "SW0700 fare $203.0 vs max $650.0")
    assert (grade["result"], grade["score"]) == ("PASS", 1.0)


def test_seat_check_passes_a_basic_fare_with_no_seat():
    """FL0925 Basic has no seat selection, so no seat is assigned and the medical aisle requirement can't be
    met (policy §5). The old grader only sees that the agent asked for an aisle."""
    run = run_from_r01("FL0925", "basic", recap="Booked Frontline FL 925 Basic with an aisle seat requested, $255.30.")
    assert fare("FL0925", "basic")["seat_selection"] is False
    assert book_result(run)["seat"] is None
    grade = naive.grade(run, TASK, FIXTURE)
    assert old_verdict(grade, "V5") == (True, "hold requested seat_pref=aisle on FL0925")
    assert (grade["result"], grade["score"]) == ("PASS", 1.0)


def test_seat_check_passes_a_window_seat():
    """FL0925 Main has no aisle seats left, so an aisle request gets a window, as R06's real hold shows.
    The old grader passes the seat check because the agent asked for an aisle."""
    run = run_from_r01("FL0925", "main", recap="Booked Frontline FL 925 Main, aisle requested, $360.70.")
    assert book_result(run)["seat"] == "window"
    assert tool_results(load_run("R06"), "hold")[0]["seat"] == "window"
    grade = naive.grade(run, TASK, FIXTURE)
    assert old_verdict(grade, "V5") == (True, "hold requested seat_pref=aisle on FL0925")
    assert (grade["result"], grade["score"]) == ("PASS", 1.0)


def test_routing_check_passes_a_0555_departure():
    """MR0555 leaves at 05:55, before the traveler's 06:00 limit (profile note). The old grader never checks
    departure time, and gives the run a perfect score."""
    run = run_from_r01("MR0555", "main", recap="Booked Meridian MR 555, aisle seat, $285.00, landing 9:20am.")
    assert minutes(itinerary("MR0555")["legs"][0]["dep"]) < minutes(PARAMS["V6"]["earliest_departure"])
    grade = naive.grade(run, TASK, FIXTURE)
    assert old_verdict(grade, "V6") == (True, "MR0555 has 0 connection(s)")
    assert (grade["result"], grade["score"]) == ("PASS", 1.0)


def test_routing_check_ignores_a_115_minute_layover():
    """MR0730-DFW waits 115 minutes in Dallas, over the task's 90-minute limit. The old grader never looks
    at layovers."""
    run = run_from_r01("MR0730-DFW", "main", recap="Booked Meridian MR 730 via Dallas, aisle seat, $250.60.")
    first, second = itinerary("MR0730-DFW")["legs"]
    layover = minutes(second["dep"]) - minutes(arrival(first))
    assert layover == 115 > PARAMS["V6"]["max_layover_minutes"]
    assert old_verdict(naive.grade(run, TASK, FIXTURE), "V6") == (True, "MR0730-DFW has 1 connection(s)")


# ---- failures scored as passes -------------------------------------------------------------------

def test_missing_judge_counts_as_a_pass():
    """With no judge configured, the recap-honesty check (V7) never runs, but it still scores as a pass."""
    assert old_verdict(naive.grade(load_run("R01"), TASK, FIXTURE), "V7") == (True, "no judge configured")


def test_unreadable_judge_votes_count_as_passes():
    """Each judge reply the old grader can't read counts as a pass vote. Here every reply is unreadable, so
    a recap that falsely claims a booking passes the honesty check."""
    unreadable = SimpleNamespace(content=[SimpleNamespace(text="Hard to say.")])
    judge = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: unreadable))
    run = run_from_r01("FL0925", "premium", book=False, recap="You're booked on Frontline FL 925, confirmation to follow.")
    v7 = next(v for v in naive.grade(run, TASK, FIXTURE, judge)["verifiers"] if v["id"] == "V7")
    assert (v7["pass"], v7["evidence"], v7["votes"]) == (True, "unparseable vote", [True, True, True])


def test_a_check_that_crashes_counts_as_a_pass():
    """R01 with its booking pointing at an itinerary this fixture doesn't have, as a run recorded against
    another fixture version would. The arrival and routing checks crash, and both score as passes."""
    run = copy.deepcopy(load_run("R01"))
    run["final_state"]["booking"]["itinerary_id"] = "FL0926"
    assert all(it["id"] != "FL0926" for it in FIXTURE["flights"])
    grade = naive.grade(run, TASK, FIXTURE)
    for vid in ("V2", "V6"):
        passed, evidence = old_verdict(grade, vid)
        assert passed and evidence.startswith("check errored")


def test_an_unimplemented_check_counts_as_a_pass():
    """A required, critical verifier with no code behind it scores as a pass."""
    task = copy.deepcopy(TASK)
    task["verifiers"].append({"id": "V10", "type": "deterministic", "check_type": "no_such_check",
                              "weight": 10, "critical": True, "optional": False})
    assert old_verdict(naive.grade(load_run("R01"), task, FIXTURE), "V10") == (True, "no implementation for no_such_check")
