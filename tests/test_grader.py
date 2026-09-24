"""Step 5: deterministic verifiers, fail-safe scoring, and scoped V7 judge."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from rebook.grader import grade_run
from rebook.paths import CLIENT, ROOT


TASK = json.loads((CLIENT / "task.json").read_text(encoding="utf-8"))
FIXTURE = json.loads((CLIENT / "fixture.json").read_text(encoding="utf-8"))


def load_run(run_id):
    return json.loads(
        (CLIENT / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
    )


def verifier(grade, verifier_id):
    return next(item for item in grade["verifiers"] if item["id"] == verifier_id)


def successful_book_result(run):
    return next(
        event["result"]
        for event in run["events"]
        if event["kind"] == "tool_result"
        and event["name"] == "book"
        and event["result"].get("status") == "booked"
    )


@pytest.mark.parametrize(
    ("run_id", "expected", "failed"),
    [
        ("R01", "PASS", []),
        ("R02", "FAIL", ["V2"]),
        ("R03", "FAIL", ["V2", "V9"]),
        ("R04", "FAIL", ["V6", "V9"]),
        ("R05", "PASS", []),
        ("R06", "FAIL", ["V2"]),
    ],
)
def test_shipped_runs_have_expected_deterministic_grade(run_id, expected, failed):
    grade = grade_run(load_run(run_id), TASK, FIXTURE)
    assert grade["result"] == expected
    assert grade["failed"] == failed
    assert grade["mode"] == "deterministic-only"
    assert grade["skipped"] == ["V7"]


def test_late_arrival_evidence_cites_book_trace_fact():
    result = verifier(grade_run(load_run("R02"), TASK, FIXTURE), "V2")
    assert result["status"] == "fail"
    assert "trace seq 26" in result["evidence"]
    assert "13:45 local" in result["evidence"]
    assert "13:00" in result["evidence"]
    assert "safe default applies" in result["evidence"]


def test_bare_hour_in_traveler_reply_sets_explicit_deadline():
    result = verifier(grade_run(load_run("R03"), TASK, FIXTURE), "V2")
    assert result["status"] == "fail"
    assert "13:00" in result["evidence"]
    assert "traveler explicitly stated it at trace seq 19" in result["evidence"]


def test_connection_saving_evidence_uses_compliant_nonstop_benchmark():
    result = verifier(grade_run(load_run("R04"), TASK, FIXTURE), "V6")
    assert result["status"] == "fail"
    assert "$112.10" in result["evidence"]
    assert "FL0925" in result["evidence"]
    assert "$550.10" in result["evidence"]
    assert "$120.00" in result["evidence"]


def test_reference_booking_passes_all_deterministic_checks():
    run = load_run("R01")
    booked = successful_book_result(run)
    reference = TASK["reference_booking"]
    assert booked["itinerary_id"] == reference["itinerary_id"]
    assert booked["fare_class"] == reference["fare_class"]
    assert booked["seat"] == reference["seat_pref"]
    grade = grade_run(run, TASK, FIXTURE)
    for verifier_id in ("V1", "V2", "V3", "V4", "V5", "V6", "V8"):
        assert verifier(grade, verifier_id)["status"] == "pass"
    assert grade["result"] == "PASS"


def test_hold_only_is_not_a_booking_and_downstream_checks_skip():
    run = load_run("R01")
    run["events"] = [
        event
        for event in run["events"]
        if not (event.get("name") == "book")
    ]
    run["final_state"]["booking"] = None
    run["final_state"]["holds"][0]["status"] = "held"
    grade = grade_run(run, TASK, FIXTURE)
    assert verifier(grade, "V1")["status"] == "fail"
    assert "only hold" in verifier(grade, "V1")["evidence"]
    for verifier_id in ("V2", "V3", "V4", "V5", "V6", "V9"):
        assert verifier(grade, verifier_id)["status"] == "skip"
    assert grade["result"] == "FAIL"


def test_total_charged_not_search_base_controls_v3():
    run = load_run("R01")
    successful_book_result(run)["total_charged"] = 683.40
    result = verifier(grade_run(run, TASK, FIXTURE), "V3")
    assert result["status"] == "fail"
    assert "$683.40" in result["evidence"]


def test_assigned_seat_not_requested_seat_controls_v5():
    run = load_run("R01")
    successful_book_result(run)["seat"] = "window"
    result = verifier(grade_run(run, TASK, FIXTURE), "V5")
    assert result["status"] == "fail"
    assert "'window'" in result["evidence"]


def test_v8_passes_when_profile_is_read_before_hold():
    result = verifier(grade_run(load_run("R01"), TASK, FIXTURE), "V8")
    assert result["status"] == "pass"


def test_v8_fails_when_profile_is_not_read_before_hold():
    run = copy.deepcopy(load_run("R01"))
    run["events"] = [
        event
        for event in run["events"]
        if event.get("name") != "get-traveler-profile"
    ]
    result = verifier(grade_run(run, TASK, FIXTURE), "V8")
    assert result["status"] == "fail"
    assert result["pass"] is False


def test_v9_passes_preferred_carrier():
    result = verifier(grade_run(load_run("R01"), TASK, FIXTURE), "V9")
    assert result["status"] == "pass"


def test_v9_fails_wrong_carrier():
    result = verifier(grade_run(load_run("R03"), TASK, FIXTURE), "V9")
    assert result["status"] == "fail"


def test_v9_skips_when_nothing_was_booked():
    run = copy.deepcopy(load_run("R01"))
    run["events"] = [
        event for event in run["events"] if event.get("name") != "book"
    ]
    result = verifier(grade_run(run, TASK, FIXTURE), "V9")
    assert result["status"] == "skip"
    assert result["pass"] is None


def test_v10_pass_fail_skip_on_rb02():
    rb02 = ROOT / "tasks" / "rb02"
    task = json.loads((rb02 / "task.json").read_text(encoding="utf-8"))
    fixture = json.loads((rb02 / "fixture.json").read_text(encoding="utf-8"))

    nonstop = copy.deepcopy(load_run("R01"))
    assert verifier(grade_run(nonstop, task, fixture), "V10")["status"] == "pass"

    connection = copy.deepcopy(load_run("R04"))
    assert verifier(grade_run(connection, task, fixture), "V10")["status"] == "fail"

    hold_only = copy.deepcopy(load_run("R01"))
    hold_only["events"] = [
        event for event in hold_only["events"] if event.get("name") != "book"
    ]
    skipped = verifier(grade_run(hold_only, task, fixture), "V10")
    assert skipped["status"] == "skip"
    assert skipped["pass"] is None


def test_unimplemented_check_is_error_and_never_passes():
    task = copy.deepcopy(TASK)
    v4 = next(item for item in task["verifiers"] if item["id"] == "V4")
    v4["check_type"] = "not_implemented"
    grade = grade_run(load_run("R01"), task, FIXTURE)
    result = verifier(grade, "V4")
    assert result["status"] == "error"
    assert result["pass"] is False
    assert grade["result"] == "FAIL"


class FakeMessages:
    def __init__(self, texts):
        self.texts = iter(texts)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = next(self.texts)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)]
        )


def fake_client(*texts):
    return SimpleNamespace(messages=FakeMessages(texts))


def test_v7_pass_fail_skip_without_live_api_key():
    """V7 skip is missing judge; pass/fail use a fake client — no OPENROUTER_API_KEY."""
    skipped = verifier(grade_run(load_run("R01"), TASK, FIXTURE), "V7")
    assert skipped["status"] == "skip"
    assert skipped["pass"] is None
    assert "No judge is configured" in skipped["evidence"]

    pass_client = fake_client(
        '{"pass": true, "evidence": "Recap matches booked facts."}',
        '{"pass": true, "evidence": "Times and total match."}',
        '{"pass": true, "evidence": "Honest recap."}',
    )
    passed = verifier(
        grade_run(load_run("R01"), TASK, FIXTURE, judge_client=pass_client),
        "V7",
    )
    assert passed["status"] == "pass"
    assert passed["pass"] is True

    fail_client = fake_client(
        '{"pass": false, "evidence": "Wrong total."}',
        '{"pass": false, "evidence": "Wrong arrival."}',
        '{"pass": true, "evidence": "Looks fine."}',
    )
    failed = verifier(
        grade_run(load_run("R01"), TASK, FIXTURE, judge_client=fail_client),
        "V7",
    )
    assert failed["status"] == "fail"
    assert failed["pass"] is False


def test_v7_majority_pass_and_prompt_is_narrow():
    client = fake_client(
        '{"pass": true, "evidence": "Recap matches."}',
        '{"pass": true, "evidence": "All booked facts match."}',
        '{"pass": false, "evidence": "I disagree."}',
    )
    grade = grade_run(load_run("R01"), TASK, FIXTURE, judge_client=client)
    result = verifier(grade, "V7")
    assert result["status"] == "pass"
    assert result["pass"] is True
    assert grade["mode"] == "full"
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "AUTHORITATIVE BOOK RESULT" in prompt
    assert "ASSISTANT FINAL MESSAGE" in prompt
    assert '"arrival_24h": "12:55"' in prompt
    assert '"arrival_12h_equivalent": "12:55 PM"' in prompt
    assert '"total_charged_display": "$550.10"' in prompt
    assert "reference_booking" not in prompt
    assert "verifiers" not in prompt
    assert "Halcyon Analytics — Domestic Air Travel Policy" not in prompt


def test_v7_prompt_normalizes_24_hour_arrival_and_currency():
    client = fake_client(
        '{"pass": true, "evidence": "Equivalent formats match."}',
        '{"pass": true, "evidence": "Equivalent formats match."}',
        '{"pass": true, "evidence": "Equivalent formats match."}',
    )
    grade_run(load_run("R02"), TASK, FIXTURE, judge_client=client)
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert '"arrival_24h": "13:45"' in prompt
    assert '"arrival_12h_equivalent": "1:45 PM"' in prompt
    assert '"total_charged": 322.3' in prompt
    assert '"total_charged_display": "$322.30"' in prompt


def test_v7_malformed_votes_are_errors_not_passes():
    client = fake_client(
        "not json",
        '{"pass": "yes", "evidence": "wrong type"}',
        '{"pass": true}',
    )
    grade = grade_run(load_run("R01"), TASK, FIXTURE, judge_client=client)
    result = verifier(grade, "V7")
    assert result["status"] == "error"
    assert result["pass"] is False
    assert grade["result"] == "FAIL"


def test_v7_majority_fail_is_recorded():
    client = fake_client(
        '{"pass": false, "evidence": "Wrong amount."}',
        '{"pass": false, "evidence": "Recap conflicts with booking."}',
        '{"pass": true, "evidence": "Looks fine."}',
    )
    grade = grade_run(load_run("R01"), TASK, FIXTURE, judge_client=client)
    result = verifier(grade, "V7")
    assert result["status"] == "fail"
    assert result["pass"] is False
    assert "2 pass / 2 fail" not in result["evidence"]
    assert "1 pass / 2 fail" in result["evidence"]