"""Replay a recorded run through the environment and compare outcomes."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from rebook.env.session import Session
from rebook.paths import CLIENT

# Confirmation numbers use an unknown client scheme; everything else must match.
IGNORE_BOOK_FIELDS = frozenset({"pnr"})


def _strip_book_pnr(result: Any) -> Any:
    if isinstance(result, dict) and "pnr" in result:
        out = copy.deepcopy(result)
        out.pop("pnr", None)
        return out
    return result


def _booking_view(booking: dict | None) -> dict | None:
    if booking is None:
        return None
    out = {k: v for k, v in booking.items() if k not in IGNORE_BOOK_FIELDS}
    return out


def replay_run(run: dict, *, client_dir: Path | None = None) -> Session:
    """Feed a shipped run's tool calls into a fresh session."""
    session = Session.reset(client_dir)
    for event in run["events"]:
        kind = event["kind"]
        if kind == "assistant_text":
            session.step({"text": event.get("text") or ""})
        elif kind == "tool_call":
            session.step({"name": event["name"], "args": event.get("args") or {}})
        # traveler_text is recorded by the original harness; ask-traveler already returns the reply.
    return session


def compare_final_state(got: dict, expected: dict) -> list[str]:
    diffs: list[str] = []
    gb, eb = _booking_view(got.get("booking")), _booking_view(expected.get("booking"))
    if gb != eb:
        diffs.append(f"booking: got={gb} expected={eb}")
    gholds = got.get("holds") or []
    eholds = expected.get("holds") or []
    if gholds != eholds:
        diffs.append(f"holds: got={gholds} expected={eholds}")
    if got.get("clarifications") != expected.get("clarifications"):
        diffs.append(
            f"clarifications: got={got.get('clarifications')} "
            f"expected={expected.get('clarifications')}"
        )
    return diffs


def compare_tool_results(session: Session, run: dict) -> list[str]:
    """Compare session tool_result events to the shipped trace (PNR ignored)."""
    diffs: list[str] = []
    got_results = [e for e in session.events if e["kind"] == "tool_result"]
    exp_results = [e for e in run["events"] if e["kind"] == "tool_result"]
    if len(got_results) != len(exp_results):
        return [
            f"tool_result count: got={len(got_results)} expected={len(exp_results)}"
        ]
    for got, exp in zip(got_results, exp_results):
        if got["name"] != exp["name"]:
            diffs.append(f"tool name mismatch: got={got['name']} expected={exp['name']}")
            continue
        g = _strip_book_pnr(got["result"])
        x = _strip_book_pnr(exp["result"])
        if g != x:
            diffs.append(f"seq~{exp.get('seq')} {exp['name']}: got={g!r} expected={x!r}")
    return diffs


def replay_and_check(run: dict, *, client_dir: Path | None = None) -> dict:
    session = replay_run(run, client_dir=client_dir)
    state_diffs = compare_final_state(session.final_state(), run["final_state"])
    tool_diffs = compare_tool_results(session, run)
    ok = not state_diffs and not tool_diffs
    return {
        "run_id": run.get("run_id"),
        "ok": ok,
        "state_diffs": state_diffs,
        "tool_diffs": tool_diffs,
        "final_state": session.final_state(),
    }


def replay_all(client_dir: Path | None = None) -> list[dict]:
    root = client_dir or CLIENT
    results = []
    for path in sorted((root / "runs").glob("R0*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        results.append(replay_and_check(run, client_dir=root))
    return results


def main() -> None:
    results = replay_all()
    failed = [r for r in results if not r["ok"]]
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        print(f"{r['run_id']}  {status}")
        for d in r["state_diffs"]:
            print(f"  state: {d}")
        for d in r["tool_diffs"][:5]:
            print(f"  tool:  {d[:200]}")
    if failed:
        raise SystemExit(f"{len(failed)}/{len(results)} runs failed replay")
    print(f"All {len(results)} runs replayed successfully (PNR ignored).")


if __name__ == "__main__":
    main()
