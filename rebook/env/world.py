"""Frozen fixture world with assistant-visible views only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from rebook.env.timeutil import arrival_local, minutes
from rebook.paths import CLIENT


def canonical_snapshot_id(fixture: dict) -> str:
    """Hash of fixture.json with meta.snapshot_id excluded (matches client runs)."""
    data = copy.deepcopy(fixture)
    if "meta" in data and isinstance(data["meta"], dict):
        data["meta"].pop("snapshot_id", None)
    blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()[:16]


class World:
    """Mutable inventory over a deep-copied fixture. Tools only see whitelisted views."""

    def __init__(self, fixture: dict, policy_text: str):
        self.raw = copy.deepcopy(fixture)
        self.policy_text = policy_text
        self.airports = self.raw["airports"]
        self.carriers = self.raw["carriers"]
        self.traveler = copy.deepcopy(self.raw["traveler"])
        self.rules = copy.deepcopy(self.raw.get("rules") or {})
        self.flights = {f["id"]: copy.deepcopy(f) for f in self.raw["flights"]}
        self.snapshot_id = self.raw.get("meta", {}).get("snapshot_id") or canonical_snapshot_id(fixture)

    @classmethod
    def load(cls, client_dir: Path | None = None) -> "World":
        root = client_dir or CLIENT
        fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        policy = (root / "policy.md").read_text(encoding="utf-8")
        return cls(fixture, policy)

    def itinerary(self, iid: str) -> dict | None:
        return self.flights.get(iid)

    def offset(self, code: str) -> float:
        return float(self.airports[code]["utc_offset_hours"])

    def leg_arr_local(self, leg: dict) -> str:
        return arrival_local(
            leg["dep"],
            leg["duration_min"],
            self.offset(leg["from"]),
            self.offset(leg["to"]),
        )

    def public_legs(self, itinerary: dict) -> list[dict]:
        out = []
        for leg in itinerary["legs"]:
            out.append(
                {
                    "flight_no": leg["flight_no"],
                    "from": leg["from"],
                    "to": leg["to"],
                    "dep_local": leg["dep"],
                    "arr_local": self.leg_arr_local(leg),
                    "duration_min": leg["duration_min"],
                }
            )
        return out

    def layovers_min(self, itinerary: dict) -> list[int]:
        legs = itinerary["legs"]
        if len(legs) < 2:
            return []
        out = []
        for i in range(len(legs) - 1):
            arr = minutes(self.leg_arr_local(legs[i]))
            dep = minutes(legs[i + 1]["dep"])
            # Same local clock at connection airport (MSP/ORD both UTC−5 in this fixture).
            gap = dep - arr
            if gap < 0:
                gap += 24 * 60
            out.append(gap)
        return out

    def lowest_available_base(self, itinerary: dict) -> tuple[float | None, str | None]:
        priced = [
            (f["base"], f["class"])
            for f in itinerary["fares"]
            if f.get("seats_left", 0) > 0
        ]
        if not priced:
            return None, None
        base, cls = min(priced, key=lambda x: x[0])
        return base, cls

    def search_itineraries(self) -> list[dict]:
        """Assistant-visible search rows — no raw rules, no grading secrets."""
        rows = []
        for it in self.flights.values():
            base, cls = self.lowest_available_base(it)
            rows.append(
                {
                    "itinerary_id": it["id"],
                    "carrier": it["carrier"],
                    "carrier_name": self.carriers.get(it["carrier"], {}).get("name", it["carrier"]),
                    "status": it["status"],
                    "stops": len(it["legs"]) - 1,
                    "legs": self.public_legs(it),
                    "layover_min": self.layovers_min(it),
                    "from_base_fare": base,
                    "from_fare_class": cls,
                }
            )
        return rows

    def public_fares(self, iid: str) -> list[dict] | None:
        it = self.itinerary(iid)
        if not it:
            return None
        fares = []
        for f in it["fares"]:
            total = round(f["base"] + f["taxes_fees"], 2)
            # Match shipped tool shape: no seat selection → aisle_seats_left is null.
            aisle = None if not f["seat_selection"] else f["aisle_seats_left"]
            fares.append(
                {
                    "class": f["class"],
                    "base": f["base"],
                    "taxes_fees": f["taxes_fees"],
                    "total": total,
                    "seats_left": f["seats_left"],
                    "seat_selection": f["seat_selection"],
                    "aisle_seats_left": aisle,
                }
            )
        return fares

    def public_profile(self) -> dict:
        """Full traveler profile as returned by get-traveler-profile (fixture field)."""
        return copy.deepcopy(self.traveler)

    def fare(self, iid: str, fare_class: str) -> dict | None:
        it = self.itinerary(iid)
        if not it:
            return None
        return next((f for f in it["fares"] if f["class"] == fare_class), None)

    def decrement_inventory(self, iid: str, fare_class: str, seat: str | None) -> None:
        f = self.fare(iid, fare_class)
        if not f or f["seats_left"] <= 0:
            raise ValueError("no seats left")
        f["seats_left"] -= 1
        if seat == "aisle" and f["aisle_seats_left"] > 0:
            f["aisle_seats_left"] -= 1

    def restore_inventory(self, iid: str, fare_class: str, seat: str | None) -> None:
        f = self.fare(iid, fare_class)
        if not f:
            return
        f["seats_left"] += 1
        if seat == "aisle":
            f["aisle_seats_left"] += 1
