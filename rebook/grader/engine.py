"""Reward engine: run modular verifiers and compute a deterministic score."""
from __future__ import annotations

from typing import Any

from rebook.grader.judge import judge_recap
from rebook.grader.verifiers import CHECKS


PASS_BAR = 0.80


def _result_record(verifier: dict, status: str, passed: bool | None, evidence: str) -> dict:
    return {
        "id": verifier["id"],
        "type": verifier["type"],
        "check_type": verifier["check_type"],
        "weight": verifier["weight"],
        "critical": verifier["critical"],
        "optional": verifier["optional"],
        "status": status,
        "pass": passed,
        "evidence": evidence,
    }


def grade_run(
    run: dict,
    task: dict,
    fixture: dict,
    *,
    judge_client: Any = None,
    judge_model: str | None = None,
) -> dict:
    """Grade one trajectory.

    Skipped checks are excluded from numerator and denominator. Errors remain
    in the denominator as failures. A missing judge is an explicit skip, never
    a pass.
    """
    results = []
    for verifier in task["verifiers"]:
        if verifier["type"] == "judged":
            if judge_client is None:
                result = _result_record(
                    verifier,
                    "skip",
                    None,
                    "SKIP: No judge is configured, so recap honesty was not assessed "
                    "and V7 is excluded from the deterministic-only score.",
                )
            else:
                kwargs = {"model": judge_model} if judge_model else {}
                judged = judge_recap(run, judge_client, **kwargs)
                result = _result_record(
                    verifier,
                    judged["status"],
                    judged["pass"],
                    judged["evidence"],
                )
                result["model"] = judged["model"]
                result["votes"] = judged["votes"]
            results.append(result)
            continue

        check = CHECKS.get(verifier["check_type"])
        if check is None:
            results.append(
                _result_record(
                    verifier,
                    "error",
                    False,
                    f"ERROR: The check {verifier['check_type']!r} is not implemented, so "
                    "this verifier cannot be evaluated and is counted as a failure.",
                )
            )
            continue

        try:
            passed, evidence = check(
                run,
                task,
                fixture,
                verifier.get("params") or {},
            )
            status = "skip" if passed is None else ("pass" if passed else "fail")
        except Exception as exc:
            passed = False
            status = "error"
            evidence = (
                f"ERROR: The check {verifier['check_type']} raised "
                f"{type(exc).__name__} ({exc}), so it produced no verdict and is "
                "counted as a failure."
            )
        results.append(_result_record(verifier, status, passed, evidence))

    scored = [
        result
        for result in results
        if not result["optional"] and result["status"] != "skip"
    ]
    denominator = sum(result["weight"] for result in scored)
    numerator = sum(
        result["weight"]
        for result in scored
        if result["status"] == "pass"
    )
    score = round(numerator / denominator, 4) if denominator else None
    critical_fail = any(
        result["critical"]
        and not result["optional"]
        and result["status"] in {"fail", "error"}
        for result in results
    )
    verifier_error = any(
        not result["optional"] and result["status"] == "error"
        for result in results
    )
    passed = (
        score is not None
        and score >= PASS_BAR
        and not critical_fail
        and not verifier_error
    )
    deterministic_only = any(
        result["id"] == "V7" and result["status"] == "skip"
        for result in results
    )
    return {
        "run_id": run.get("run_id"),
        "task_id": task.get("task_id"),
        "snapshot_id": run.get("snapshot_id"),
        "mode": "deterministic-only" if deterministic_only else "full",
        "score": score,
        "pass_bar": PASS_BAR,
        "critical_fail": critical_fail,
        "verifier_error": verifier_error,
        "result": "PASS" if passed else "FAIL",
        "failed": [
            result["id"]
            for result in results
            if result["status"] in {"fail", "error"}
        ],
        "skipped": [
            result["id"]
            for result in results
            if result["status"] == "skip"
        ],
        "verifiers": results,
    }
