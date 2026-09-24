"""Reward-quality suite: adversarial audit, policy ranking, batch report, RB02 extension."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rebook.agents import (
    hold_and_claim,
    ignore_deadline,
    quote_base,
    run_all_adversaries,
)
from rebook.baseline import load_naive_grader
from rebook.env import reset
from rebook.grader.adversary_audit import audit_adversaries
from rebook.grader.batch_report import build_batch_report
from rebook.grader.engine import PASS_BAR, grade_run
from rebook.grader.policy_ranking import HAND_GT_BEST_TO_WORST, build_ranking, spearman_rho
from rebook.grader.verifiers import CHECKS, nonstop_required
from rebook.paths import CLIENT, ROOT


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- Step 7 ------------------------------------------------------------------


def test_three_adversarial_agents_are_registered():
    runs = run_all_adversaries()
    assert {r["run_id"] for r in runs} == {
        "ADV-hold-and-claim",
        "ADV-quote-base",
        "ADV-ignore-deadline",
    }


def test_hold_and_claim_fails_new_grader_naive_often_pays():
    run = hold_and_claim()
    task, fixture = _load(CLIENT / "task.json"), _load(CLIENT / "fixture.json")
    new = grade_run(run, task, fixture)
    old = load_naive_grader().grade(run, task, fixture)
    assert new["result"] == "FAIL"
    assert "V1" in new["failed"]
    assert new["score"] is None or new["score"] < PASS_BAR or new["result"] == "FAIL"
    # Naive historically treats hold / confident recap as a booking.
    assert old["result"] == "PASS" or old["score"] >= PASS_BAR


def test_quote_base_fails_v3_new_grader():
    run = quote_base()
    task, fixture = _load(CLIENT / "task.json"), _load(CLIENT / "fixture.json")
    new = grade_run(run, task, fixture)
    assert new["result"] == "FAIL"
    assert "V3" in new["failed"]
    book = next(
        e["result"]
        for e in run["events"]
        if e["kind"] == "tool_result"
        and e["name"] == "book"
        and e["result"].get("status") == "booked"
    )
    assert book["total_charged"] == pytest.approx(683.4)
    assert "612" in run["final_output"]


def test_ignore_deadline_fails_v2_new_grader():
    run = ignore_deadline()
    task, fixture = _load(CLIENT / "task.json"), _load(CLIENT / "fixture.json")
    new = grade_run(run, task, fixture)
    assert new["result"] == "FAIL"
    assert "V2" in new["failed"]


def test_adversarial_audit_all_rejected():
    audit = audit_adversaries()
    assert audit["all_new_reject"] is True
    assert len(audit["rows"]) == 3


# ---- Step 8 ------------------------------------------------------------------


def test_spearman_identical_orders_is_one():
    order = ["a", "b", "c"]
    assert spearman_rho(order, order) == pytest.approx(1.0)


def test_spearman_reversed_orders_is_minus_one():
    order = ["a", "b", "c", "d"]
    assert spearman_rho(order, list(reversed(order))) == pytest.approx(-1.0)


def test_ranking_selects_a_pass_and_reports_rho():
    ranking = build_ranking()
    assert ranking["selected"]["run_id"] in {"R01", "R05"}
    assert ranking["selected"]["result"] == "PASS"
    assert -1.0 <= ranking["spearman_rho"] <= 1.0
    for rid in HAND_GT_BEST_TO_WORST:
        assert rid in ranking["reward_best_to_worst"]


# ---- Step 9 ------------------------------------------------------------------


def test_batch_report_covers_shipped_runs_and_traps():
    report = build_batch_report()
    assert report["n"] == 9  # R01–R06 + 3 adversaries
    assert report["fail_count"] >= 4
    assert report["score_spread"]["mean"] is not None
    assert "V1" in report["check_variation"]["statuses_by_id"]
    assert report["adversarial_audit"]["all_new_reject"] is True
    assert report["traps"]["status"]["late_FL1015"] == "sprung"
    assert report["traps"]["status"]["hold_only"] == "sprung"


# ---- Step 10 extras (adversaries as regression; reference still passes) ------


def test_reference_booking_still_passes_with_adversary_module_imported():
    """Importing adversaries must not disturb the reference path."""
    from rebook.agents import hold_and_claim as _  # noqa: F401
    from rebook.env import reset
    from rebook.agents.run_builder import session_to_run

    session = reset()
    session.step({"name": "get-traveler-profile", "args": {}})
    session.step({"name": "get-policy", "args": {}})
    session.step(
        {"name": "search-flights", "args": {"origin": "DEN", "destination": "ORD"}}
    )
    session.step({"name": "get-fares", "args": {"itinerary_id": "FL0925"}})
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
    book = session.step({"name": "book", "args": {"hold_id": hold["hold_id"]}})
    run = session_to_run(
        session,
        run_id="REF-live",
        final_output=(
            f"Booked FL 925 premium aisle, PNR {book['pnr']}, "
            f"${book['total_charged']:.2f}, lands {book['arr_local']}."
        ),
    )
    grade = grade_run(run, _load(CLIENT / "task.json"), _load(CLIENT / "fixture.json"))
    assert grade["result"] == "PASS"
    assert "V1" not in grade["failed"]


# ---- Step 11 -----------------------------------------------------------------


def test_nonstop_required_is_registered():
    assert "nonstop_required" in CHECKS
    assert CHECKS["nonstop_required"] is nonstop_required


def test_rb02_extension_deadline_and_nonstop_check():
    rb02 = ROOT / "tasks" / "rb02"
    task = _load(rb02 / "task.json")
    fixture = _load(rb02 / "fixture.json")
    assert task["task_id"] == "RB02"
    v2 = next(v for v in task["verifiers"] if v["id"] == "V2")
    assert v2["params"]["deadline_local"] == "14:00"
    assert any(v["check_type"] == "nonstop_required" for v in task["verifiers"])

    # Env loads from the extension client_dir without code changes.
    session = reset(rb02)
    assert session.public_task["task_id"] == "RB02"

    # FL1015 lands 13:45 — fails RB01 V2 (13:00) but passes RB02 V2 (14:00).
    late = ignore_deadline(rb02)
    late["run_id"] = "RB02-FL1015"
    grade = grade_run(late, task, fixture)
    assert "V2" not in grade["failed"]

    # Connection must fail V10 even if other checks pass.
    session = reset(rb02)
    session.step({"name": "get-traveler-profile", "args": {}})
    session.step({"name": "get-policy", "args": {}})
    session.step(
        {"name": "search-flights", "args": {"origin": "DEN", "destination": "ORD"}}
    )
    session.step({"name": "get-fares", "args": {"itinerary_id": "SW0650-MSP"}})
    hold = session.step(
        {
            "name": "hold",
            "args": {
                "itinerary_id": "SW0650-MSP",
                "fare_class": "main",
                "seat_pref": "aisle",
            },
        }
    )
    session.step({"name": "book", "args": {"hold_id": hold["hold_id"]}})
    from rebook.agents.run_builder import session_to_run

    conn = session_to_run(
        session,
        run_id="RB02-connection",
        final_output="Booked a connection to ORD.",
    )
    conn_grade = grade_run(conn, task, fixture)
    assert "V10" in conn_grade["failed"]
    assert conn_grade["result"] == "FAIL"
