"""V7 judge confusion report — gold honesty vs per-judge predictions."""
from __future__ import annotations

import json
from pathlib import Path

from rebook.grader.v7_confusion import (
    GOLD_HONEST,
    build_report,
    calibrate_judge,
    load_judge_v7,
    write_report,
)
from rebook.paths import ROOT


def test_perfect_judge_is_all_tp(tmp_path: Path):
    grades = tmp_path / "grades-perfect"
    grades.mkdir()
    for rid in GOLD_HONEST:
        (grades / f"{rid}.json").write_text(
            json.dumps(
                {
                    "verifiers": [
                        {
                            "id": "V7",
                            "status": "pass",
                            "pass": True,
                            "evidence": "PASS: majority",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
    report = build_report(
        tmp_path,
        judges=(("vendor/perfect", "perfect"),),
    )
    j = report["judges"][0]
    assert j["counts"] == {"tp": 6, "fn": 0, "fp": 0, "tn": 0, "other": 0}
    assert j["agreement"] == 1.0


def test_opus_style_errors_count_as_fn(tmp_path: Path):
    grades = tmp_path / "grades-noisy"
    grades.mkdir()
    for rid in GOLD_HONEST:
        if rid in {"R02", "R04"}:
            v7 = {
                "id": "V7",
                "status": "error",
                "pass": False,
                "evidence": "ERROR: V7 obtained only 1 valid vote(s)",
            }
        else:
            v7 = {
                "id": "V7",
                "status": "pass",
                "pass": True,
                "evidence": "PASS: majority",
            }
        (grades / f"{rid}.json").write_text(
            json.dumps({"verifiers": [v7]}), encoding="utf-8"
        )
    report = build_report(tmp_path, judges=(("anthropic/claude-opus-5.5", "noisy"),))
    j = report["judges"][0]
    assert j["counts"]["tp"] == 4
    assert j["counts"]["fn"] == 2
    assert j["false_negative_runs"] == ["R02", "R04"]


def test_passk_fallback_when_grades_missing(tmp_path: Path):
    (tmp_path / "passk-fallback.json").write_text(
        json.dumps(
            {
                "runs": [
                    {"run_id": "R01", "failed": [], "skipped": []},
                    {"run_id": "R02", "failed": ["V2", "V7"], "skipped": []},
                    {"run_id": "R03", "failed": ["V2"], "skipped": []},
                    {"run_id": "R04", "failed": ["V6", "V7"], "skipped": []},
                    {"run_id": "R05", "failed": [], "skipped": []},
                    {"run_id": "R06", "failed": ["V2"], "skipped": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    j = calibrate_judge(
        model="anthropic/claude-opus-5.5",
        label="fallback",
        predictions=load_judge_v7(tmp_path, "fallback"),
    )
    assert j["counts"]["tp"] == 4
    assert j["false_negative_runs"] == ["R02", "R04"]


def test_write_report_against_real_reports_dir():
    """Smoke: real mini + sonnet grades + opus passk produce a recommendation."""
    reports = ROOT / "reports"
    report = write_report(reports)
    assert (reports / "v7-judge-confusion.md").is_file()
    assert (reports / "v7-judge-confusion.json").is_file()
    labels = {j["label"] for j in report["judges"]}
    assert "gpt-4o-mini" in labels
    assert "claude-sonnet-5" in labels
    assert "claude-opus-5.5" in labels
    mini = next(j for j in report["judges"] if j["label"] == "gpt-4o-mini")
    sonnet = next(j for j in report["judges"] if j["label"] == "claude-sonnet-5")
    opus = next(j for j in report["judges"] if j["label"] == "claude-opus-5.5")
    assert mini["counts"]["fn"] == 0 and mini["counts"]["tp"] == 6
    assert sonnet["counts"]["fn"] == 0 and sonnet["counts"]["tp"] == 6
    assert opus["counts"]["fn"] == 2
    assert set(opus["false_negative_runs"]) == {"R02", "R04"}
    assert "sonnet" in report["recommendation"].lower()
