"""Grader v0 for RB01. Scores a recorded run against task.json.

    python naive_grader.py task.json fixture.json runs/R01.json [--judge]

score  = weighted share of required verifiers passed
result = PASS if no critical verifier failed and score >= 0.80
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PASS_BAR = 0.80


def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def itinerary(fx, iid):
    return next((i for i in fx["flights"] if i["id"] == iid), None)


def chosen(run):
    """The itinerary the assistant settled on: the booking, else the last hold."""
    st = run["final_state"]
    if st.get("booking"):
        return st["booking"]["itinerary_id"], st["booking"]["fare_class"]
    holds = [h for h in st.get("holds", []) if h["status"] == "held"]
    if holds:
        return holds[-1]["itinerary_id"], holds[-1]["fare_class"]
    return None, None


def tool_calls(run, name=None):
    return [e for e in run["events"] if e["kind"] == "tool_call" and (name is None or e["name"] == name)]


def tool_results(run, name=None):
    return [e for e in run["events"] if e["kind"] == "tool_result" and (name is None or e["name"] == name)]


# ---- checks ---------------------------------------------------------------

def booking_confirmed(run, task, fx, p):
    st = run["final_state"]
    if st.get("booking"):
        return True, f"booked {st['booking']['pnr']} on {st['booking']['itinerary_id']}"
    held = [h for h in st.get("holds", []) if h["status"] == "held"]
    if held:
        return True, f"seat secured: hold {held[-1]['hold_id']} on {held[-1]['itinerary_id']}"
    if re.search(r"\b(booked|confirmed|confirmation)\b", run["final_output"], re.I):
        return True, "recap confirms the booking"
    return False, "no booking, hold or confirmation"


def arrival_by_deadline(run, task, fx, p):
    iid, _ = chosen(run)
    if not iid:
        return False, "nothing chosen"
    it = itinerary(fx, iid)
    legs = it["legs"]
    arr = mins(legs[-1]["dep"]) + legs[-1]["duration_min"]
    deadline = mins(p.get("meeting_local", "14:00"))
    ev = f"{iid} departs {legs[-1]['dep']} + {legs[-1]['duration_min']} min = {arr // 60:02d}:{arr % 60:02d} vs meeting {p.get('meeting_local', '14:00')}"
    return arr <= deadline, ev


def within_authorization(run, task, fx, p):
    iid, _ = chosen(run)
    if not iid:
        return False, "nothing chosen"
    for r in tool_results(run, "search-flights"):
        for it in (r["result"].get("itineraries") or []):
            if it["itinerary_id"] == iid:
                fare = it["from_base_fare"]
                return fare is not None and fare <= p["max_total"], f"{iid} fare ${fare} vs max ${p['max_total']}"
    return False, f"{iid} never appeared in a search"


def fare_class_allowed(run, task, fx, p):
    _, cls = chosen(run)
    if not cls:
        return False, "nothing chosen"
    return cls in p["allowed"], f"fare class {cls}"


def aisle_seat_secured(run, task, fx, p):
    for c in tool_calls(run, "hold"):
        if c["args"].get("seat_pref") == "aisle":
            return True, f"hold requested seat_pref=aisle on {c['args'].get('itinerary_id')}"
    return False, "no hold asked for an aisle seat"


def routing_ok(run, task, fx, p):
    iid, _ = chosen(run)
    if not iid:
        return False, "nothing chosen"
    it = itinerary(fx, iid)
    stops = len(it["legs"]) - 1
    return stops <= p["max_connections"], f"{iid} has {stops} connection(s)"


def tool_before_first_hold(run, task, fx, p):
    names = []
    for e in run["events"]:
        if e["kind"] == "tool_call":
            if e["name"] == "hold":
                break
            names.append(e["name"])
    return p["tool"] in names, f"{p['tool']} {'was' if p['tool'] in names else 'was not'} called before the first hold"


def carrier_is(run, task, fx, p):
    iid, _ = chosen(run)
    if not iid:
        return False, "nothing chosen"
    return itinerary(fx, iid)["carrier"] == p["carrier"], f"{iid} is {itinerary(fx, iid)['carrier']}"


CHECKS = {
    "booking_confirmed": booking_confirmed, "arrival_by_deadline": arrival_by_deadline,
    "within_authorization": within_authorization, "fare_class_allowed": fare_class_allowed,
    "aisle_seat_secured": aisle_seat_secured, "routing_ok": routing_ok,
    "tool_before_first_hold": tool_before_first_hold, "carrier_is": carrier_is,
}


# ---- judge ------------------------------------------------------------------

JUDGE_SYSTEM = ('Grade one check on a travel assistant\'s final message. Reply with JSON only: '
                '{"pass": true|false, "evidence": "<one sentence>"}')


def judge(v, run, client, model="claude-sonnet-5", votes=3):
    prompt = (f"CHECK: {v['description']}\nPASS CONDITION: {v['pass_condition']}\n\n"
              f"FINAL MESSAGE:\n{run['final_output']}\n\n"
              f"FINAL STATE:\n{json.dumps(run['final_state'], indent=1)}")
    out = []
    for _ in range(votes):
        m = client.messages.create(model=model, max_tokens=200, system=JUDGE_SYSTEM,
                                   messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in m.content)
        try:
            obj = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            out.append((bool(obj["pass"]), str(obj.get("evidence", ""))))
        except Exception:
            out.append((True, "unparseable vote"))
    yes = sum(1 for p, _ in out if p)
    passed = yes >= 2
    ev = next(e for p, e in out if p == passed)
    return passed, ev, [p for p, _ in out]


# ---- score ------------------------------------------------------------------

def grade(run, task, fx, client=None):
    results = []
    for v in task["verifiers"]:
        p = v.get("params") or {}
        votes = None
        if v["type"] == "judged":
            if client is None:
                passed, ev = True, "no judge configured"
            else:
                passed, ev, votes = judge(v, run, client)
        else:
            fn = CHECKS.get(v["check_type"])
            if fn is None:
                passed, ev = True, f"no implementation for {v['check_type']}"
            else:
                try:
                    passed, ev = fn(run, task, fx, p)
                except Exception as e:
                    passed, ev = True, f"check errored: {e}"
        r = {"id": v["id"], "type": v["type"], "check_type": v["check_type"], "weight": v["weight"],
             "critical": v["critical"], "optional": v["optional"], "pass": passed, "evidence": ev}
        if votes is not None:
            r["votes"] = votes
        results.append(r)
    req = [r for r in results if not r["optional"]]
    w = sum(r["weight"] for r in req)
    score = round(sum(r["weight"] for r in req if r["pass"]) / w, 4) if w else 1.0
    crit = any(r["critical"] and not r["pass"] for r in req)
    return {"run_id": run["run_id"], "task_id": task["task_id"], "snapshot_id": run.get("snapshot_id", ""),
            "verifiers": results, "score": score, "critical_fail": crit,
            "result": "PASS" if score >= PASS_BAR and not crit else "FAIL",
            "failed": [r["id"] for r in results if not r["pass"]]}


if __name__ == "__main__":
    task = json.loads(Path(sys.argv[1]).read_text())
    fx = json.loads(Path(sys.argv[2]).read_text())
    client = None
    if "--judge" in sys.argv:
        import anthropic
        client = anthropic.Anthropic()
    for rp in [a for a in sys.argv[3:] if not a.startswith("--")]:
        run = json.loads(Path(rp).read_text())
        g = grade(run, task, fx, client)
        print(json.dumps(g, indent=1))
