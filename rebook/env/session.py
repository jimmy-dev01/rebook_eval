"""Episode session: reset / step over the eight airline tools."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from rebook.env.world import World
from rebook.paths import CLIENT
from rebook.privacy import assert_no_leakage, public_task_view


TOOL_NAMES = (
    "get-traveler-profile",
    "get-policy",
    "search-flights",
    "get-fares",
    "hold",
    "cancel-hold",
    "book",
    "ask-traveler",
)


def _pnr_for(hold_id: str, itinerary_id: str, fare_class: str) -> str:
    digest = hashlib.sha256(f"{hold_id}:{itinerary_id}:{fare_class}".encode()).hexdigest().upper()
    return "R" + digest[:5]


class Session:
    """One episode. Tools never receive private task fields."""

    def __init__(self, world: World, public_task: dict):
        self.world = world
        self.public_task = public_task
        self.events: list[dict] = []
        self._seq = 0
        self.holds: dict[str, dict] = {}
        self.booking: dict | None = None
        self.clarifications = 0
        self.max_clarifications = int(public_task.get("max_clarifications", 2))
        self._hold_n = 0

    @classmethod
    def reset(cls, client_dir: Path | None = None) -> "Session":
        root = client_dir or CLIENT
        world = World.load(root)
        task = json.loads((root / "task.json").read_text(encoding="utf-8"))
        return cls(world, public_task_view(task))

    def observation(self) -> dict:
        """What the agent may see at episode start — no grading secrets."""
        return {
            "task_id": self.public_task.get("task_id"),
            "user_message": self.public_task.get("user_message"),
            "snapshot_id": self.world.snapshot_id,
            "tools": list(TOOL_NAMES),
        }

    def final_state(self) -> dict:
        booking = None
        if self.booking:
            booking = copy.deepcopy(self.booking)
        holds = []
        for h in self.holds.values():
            holds.append(
                {
                    "hold_id": h["hold_id"],
                    "itinerary_id": h["itinerary_id"],
                    "fare_class": h["fare_class"],
                    "seat": h.get("seat"),
                    "total": h["total"],
                    "status": h["status"],
                }
            )
        return {
            "booking": booking,
            "holds": holds,
            "clarifications": self.clarifications,
        }

    def _record(self, kind: str, **payload) -> dict:
        self._seq += 1
        event = {"seq": self._seq, "kind": kind, **payload}
        self.events.append(event)
        return event

    def step(self, action: dict) -> dict:
        """Apply one agent action. action = {name, args} or assistant text."""
        if "text" in action and "name" not in action:
            self._record("assistant_text", text=action["text"])
            return {"ok": True, "event_kind": "assistant_text"}

        name = action["name"]
        args = action.get("args") or {}
        self._record("tool_call", name=name, args=copy.deepcopy(args))
        try:
            result = self._dispatch(name, args)
        except Exception as exc:  # noqa: BLE001 — surface as tool error payload
            result = {"error": str(exc)}
        assert_no_leakage(result, where=f"tool_result:{name}")
        self._record("tool_result", name=name, result=copy.deepcopy(result))
        return result

    def _dispatch(self, name: str, args: dict) -> Any:
        if name == "get-traveler-profile":
            return self.world.public_profile()
        if name == "get-policy":
            return {"policy": self.world.policy_text}
        if name == "search-flights":
            date = self.world.raw.get("meta", {}).get("travel_date")
            return {"date": date, "itineraries": self.world.search_itineraries()}
        if name == "get-fares":
            iid = args.get("itinerary_id")
            fares = self.world.public_fares(iid)
            if fares is None:
                return {"error": f"unknown itinerary {iid}"}
            return {"itinerary_id": iid, "fares": fares}
        if name == "hold":
            return self._hold(args)
        if name == "cancel-hold":
            return self._cancel_hold(args)
        if name == "book":
            return self._book(args)
        if name == "ask-traveler":
            return self._ask_traveler(args)
        return {"error": f"unknown tool {name}"}

    def _hold(self, args: dict) -> dict:
        if self.booking:
            return {"error": "already booked"}
        iid = args.get("itinerary_id")
        fare_class = args.get("fare_class")
        seat_pref = args.get("seat_pref")
        it = self.world.itinerary(iid)
        if not it:
            return {"error": f"unknown itinerary {iid}"}
        if it["status"] != "scheduled":
            return {"error": f"itinerary {iid} is {it['status']}"}
        fare = self.world.fare(iid, fare_class)
        if not fare:
            return {"error": f"unknown fare class {fare_class}"}
        if fare["seats_left"] <= 0:
            return {"error": "no seats left"}

        seat = None
        note = None
        if not fare["seat_selection"]:
            seat = None
            note = "seat assigned at check-in; this fare class has no seat selection"
        elif seat_pref == "aisle" and fare["aisle_seats_left"] > 0:
            seat = "aisle"
        elif seat_pref == "aisle" and fare["aisle_seats_left"] <= 0:
            seat = "window"
            note = "no aisle seats remain in this fare class; window assigned"
        elif seat_pref:
            seat = seat_pref if fare["seats_left"] > 0 else None
        else:
            seat = "window" if fare["seats_left"] > 0 else None

        self.world.decrement_inventory(iid, fare_class, seat if seat == "aisle" else None)

        self._hold_n += 1
        hold_id = f"H{self._hold_n}"
        total = round(fare["base"] + fare["taxes_fees"], 2)
        hold = {
            "hold_id": hold_id,
            "itinerary_id": iid,
            "fare_class": fare_class,
            "seat": seat,
            "base": fare["base"],
            "taxes_fees": fare["taxes_fees"],
            "total": total,
            "expires_in_minutes": int(self.world.rules.get("hold_minutes", 30)),
            "status": "held",
        }
        if note:
            hold["note"] = note
        self.holds[hold_id] = hold
        return copy.deepcopy(hold)

    def _cancel_hold(self, args: dict) -> dict:
        hold_id = args.get("hold_id")
        hold = self.holds.get(hold_id)
        if not hold or hold["status"] != "held":
            return {"error": f"no active hold {hold_id}"}
        self.world.restore_inventory(hold["itinerary_id"], hold["fare_class"], hold.get("seat"))
        hold["status"] = "cancelled"
        return {"hold_id": hold_id, "status": "cancelled"}

    def _book(self, args: dict) -> dict:
        if self.booking:
            return {"error": "already booked"}
        hold_id = args.get("hold_id")
        hold = self.holds.get(hold_id)
        if not hold or hold["status"] != "held":
            return {"error": f"no active hold {hold_id}"}
        it = self.world.itinerary(hold["itinerary_id"])
        legs = self.world.public_legs(it)
        pnr = _pnr_for(hold_id, hold["itinerary_id"], hold["fare_class"])
        booking = {
            "status": "booked",
            "pnr": pnr,
            "itinerary_id": hold["itinerary_id"],
            "carrier": it["carrier"],
            "fare_class": hold["fare_class"],
            "seat": hold.get("seat"),
            "total_charged": hold["total"],
            "legs": legs,
            "arr_local": legs[-1]["arr_local"],
        }
        hold["status"] = "booked"
        self.booking = {
            "pnr": pnr,
            "itinerary_id": hold["itinerary_id"],
            "carrier": it["carrier"],
            "fare_class": hold["fare_class"],
            "seat": hold.get("seat"),
            "total_charged": hold["total"],
            "legs": legs,
            "arr_local": legs[-1]["arr_local"],
        }
        return copy.deepcopy(booking)

    def _ask_traveler(self, args: dict) -> dict:
        if self.clarifications >= self.max_clarifications:
            return {"error": "no clarifications remaining", "clarifications_remaining": 0}
        question = (args.get("question") or "").lower()
        reply = self.public_task.get("default_reply", "")
        for sr in self.public_task.get("scripted_replies") or []:
            keywords = sr.get("keywords") or []
            if any(k.lower() in question for k in keywords):
                reply = sr["reply"]
                break
        self.clarifications += 1
        remaining = self.max_clarifications - self.clarifications
        return {"reply": reply, "clarifications_remaining": remaining}


def reset(client_dir: Path | None = None) -> Session:
    return Session.reset(client_dir)
