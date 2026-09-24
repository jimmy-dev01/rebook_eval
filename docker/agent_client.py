#!/usr/bin/env python3
"""Minimal HTTP client for the RB01 evaluator — deliberately zero-dependency.

This file has no import of `rebook` at all. That is the point: the agent
image (`Dockerfile.agent`) copies *only this one file* onto an otherwise
empty base image. There is no `rebook-sample-package/` (fixture, task,
policy) and no `rebook/grader` in this image for a curious or adversarial
agent process to open, `import`, or find on disk — the only way this
container can act in the world is the HTTP calls below, to the evaluator
service on the other side of the Docker network.

Run inside the container as:
    python agent_client.py --base-url http://evaluator:8000 [--demo]

`--demo` plays the reference booking (get-traveler-profile, get-policy,
hold FL0925 premium aisle, book) purely through the HTTP API, and prints the
transcript, to prove the round trip works without local file access.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


class EvaluatorClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session_id: str | None = None

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8"))

    def reset(self) -> dict:
        body = self._post("/reset", {})
        self.session_id = body["session_id"]
        return body["observation"]

    def call(self, name: str, args: dict | None = None) -> dict:
        if not self.session_id:
            raise RuntimeError("call reset() first")
        body = self._post(
            "/step", {"session_id": self.session_id, "action": {"name": name, "args": args or {}}}
        )
        return body.get("result", body)


def run_demo(base_url: str) -> None:
    client = EvaluatorClient(base_url)
    obs = client.reset()
    print("observation:", json.dumps(obs, indent=2))

    profile = client.call("get-traveler-profile")
    print("profile:", json.dumps(profile, indent=2))

    held = client.call(
        "hold",
        {"itinerary_id": "FL0925", "fare_class": "premium", "seat_pref": "aisle"},
    )
    print("hold:", json.dumps(held, indent=2))

    if held.get("hold_id"):
        booked = client.call("book", {"hold_id": held["hold_id"]})
        print("book:", json.dumps(booked, indent=2))
        if booked.get("status") == "booked":
            print(f"\nBooked {booked['itinerary_id']} {booked['fare_class']} "
                  f"for ${booked['total_charged']:.2f}, PNR {booked['pnr']}.")
            print("This container never opened fixture.json, task.json, or policy.md.")


def main() -> None:
    parser = argparse.ArgumentParser(description="RB01 agent-side HTTP client")
    parser.add_argument("--base-url", default="http://evaluator:8000")
    parser.add_argument("--demo", action="store_true", help="play the reference booking and exit")
    args = parser.parse_args()
    if args.demo:
        run_demo(args.base_url)
    else:
        print(f"Client ready. Import EvaluatorClient and drive it from your own agent code.")
        print(f"Evaluator base URL: {args.base_url}")


if __name__ == "__main__":
    main()
