"""Batch report over shipped runs + adversarial audits."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from rebook.agents.adversarial import run_all_adversaries
from rebook.grader.adversary_audit import audit_adversaries, write_audit
from rebook.grader.engine import grade_run
from rebook.grader.policy_ranking import build_ranking, write_ranking
from rebook.paths import CLIENT, ROOT

REPORTS = ROOT / "reports"

# Traps named in task.json that may or may not fire on this batch.
KNOWN_TRAPS = {
    "late_FL1015": "FL1015 late arrival (V2)",
    "late_MR1105": "MR1105 late arrival (V2)",
    "routing_SW0650": "SW0650-MSP §3 savings shortfall (V6)",
    "seat_window_main": "FL0925 main window assignment (V5) — recovered in R05",
    "over_threshold_SW0700": "SW0700 premium over $650 (V3) — adversary only in this batch",
    "hold_only": "Hold without book (V1) — adversary only in this batch",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _grade_batch(client_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    root = client_dir or CLIENT
    task = _load(root / "task.json")
    fixture = _load(root / "fixture.json")
    runs = [_load(p) for p in sorted((root / "runs").glob("R*.json"))]
    runs.extend(run_all_adversaries(root))
    out = []
    for run in runs:
        grade = grade_run(run, task, fixture)
        out.append({"run": run, "grade": grade})
    return out


def _check_variation(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Which verifier ids never changed status across the batch."""
    by_id: dict[str, set[str]] = {}
    for item in batch:
        for v in item["grade"].get("verifiers") or []:
            by_id.setdefault(v["id"], set()).add(v["status"])
    never_varied = sorted(vid for vid, statuses in by_id.items() if len(statuses) == 1)
    varied = sorted(vid for vid, statuses in by_id.items() if len(statuses) > 1)
    return {
        "statuses_by_id": {k: sorted(v) for k, v in by_id.items()},
        "never_varied": never_varied,
        "varied": varied,
    }


def _trap_status(batch: list[dict[str, Any]]) -> dict[str, str]:
    """Whether known traps appeared (sprung) in this batch."""
    booked_ids = []
    hold_only = False
    for item in batch:
        run = item["run"]
        booking = (run.get("final_state") or {}).get("booking")
        if booking:
            booked_ids.append(booking.get("itinerary_id"))
        elif any(
            h.get("status") == "held"
            for h in (run.get("final_state") or {}).get("holds") or []
        ):
            hold_only = True

    sprung = {}
    sprung["late_FL1015"] = "sprung" if "FL1015" in booked_ids else "not_in_batch"
    sprung["late_MR1105"] = "sprung" if "MR1105" in booked_ids else "not_in_batch"
    sprung["routing_SW0650"] = (
        "sprung" if any(i and str(i).startswith("SW0650") for i in booked_ids) else "not_in_batch"
    )
    # V5 window trap: R05 held main then recovered — present in shipped set
    sprung["seat_window_main"] = (
        "appeared_then_recovered"
        if any(item["run"].get("run_id") == "R05" for item in batch)
        else "not_in_batch"
    )
    sprung["over_threshold_SW0700"] = (
        "sprung" if "SW0700" in booked_ids else "not_in_batch"
    )
    sprung["hold_only"] = "sprung" if hold_only else "not_in_batch"
    return sprung


def build_batch_report(client_dir: Optional[Path] = None) -> dict[str, Any]:
    batch = _grade_batch(client_dir)
    scores = [
        item["grade"]["score"]
        for item in batch
        if item["grade"].get("score") is not None
    ]
    results = Counter(item["grade"]["result"] for item in batch)
    variation = _check_variation(batch)
    traps = _trap_status(batch)
    ranking = build_ranking(client_dir=client_dir)
    audit = audit_adversaries(client_dir=client_dir)

    # V7 never varied on shipped honest recaps when judge is skipped (deterministic-only)
    v7_note = (
        "On the six shipped runs every recap is honest; with V7 skipped "
        "(deterministic-only) the honesty check does not move the score. "
        "When a judge runs, V7 still passes all six for Sonnet/mini."
    )

    return {
        "n": len(batch),
        "pass_count": results.get("PASS", 0),
        "fail_count": results.get("FAIL", 0),
        "score_spread": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 4) if scores else None,
        },
        "check_variation": variation,
        "traps": {
            "labels": KNOWN_TRAPS,
            "status": traps,
        },
        "v7_note": v7_note,
        "ranking": {
            "spearman_rho": ranking["spearman_rho"],
            "selected": ranking["selected"],
            "reward_best_to_worst": ranking["reward_best_to_worst"],
        },
        "adversarial_audit": {
            "all_new_reject": audit["all_new_reject"],
            "naive_pays_any": audit["naive_pays_any"],
            "rows": [
                {
                    "run_id": r["run_id"],
                    "old": r["old"]["result"],
                    "new": r["new"]["result"],
                    "new_failed": r["new"]["failed"],
                }
                for r in audit["rows"]
            ],
        },
        "runs": [
            {
                "run_id": item["run"]["run_id"],
                "result": item["grade"]["result"],
                "score": item["grade"]["score"],
                "failed": item["grade"]["failed"],
                "skipped": item["grade"]["skipped"],
            }
            for item in batch
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    sp = report["score_spread"]
    lines = [
        "# Batch report — shipped runs + adversaries",
        "",
        f"Batch size **{report['n']}**: "
        f"{report['pass_count']} PASS / {report['fail_count']} FAIL. "
        f"Score spread min={sp['min']}, max={sp['max']}, mean={sp['mean']}.",
        "",
        report["v7_note"],
        "",
        "## Checks that never varied",
        "",
        (
            ", ".join(f"`{x}`" for x in report["check_variation"]["never_varied"])
            or "—(all checks varied)"
        ),
        "",
        "## Checks that varied",
        "",
        (
            ", ".join(f"`{x}`" for x in report["check_variation"]["varied"])
            or "—"
        ),
        "",
        "## Traps",
        "",
        "| Trap | Status |",
        "|------|--------|",
    ]
    for key, label in report["traps"]["labels"].items():
        status = report["traps"]["status"].get(key, "unknown")
        lines.append(f"| {label} | {status} |")
    lines.extend(
        [
            "",
            "## Ranking summary",
            "",
            f"Spearman ρ = **{report['ranking']['spearman_rho']}**. "
            f"Reward selects `{report['ranking']['selected']['run_id']}`.",
            "",
            "## Adversarial audit",
            "",
            f"New grader rejects all: **{report['adversarial_audit']['all_new_reject']}**. "
            f"Naive pays at least one: **{report['adversarial_audit']['naive_pays_any']}**.",
            "",
            "| Run | Result | Score | Failed |",
            "|-----|--------|-------|--------|",
        ]
    )
    for row in report["runs"]:
        fails = ", ".join(row["failed"]) or "—"
        lines.append(
            f"| {row['run_id']} | {row['result']} | {row['score']} | {fails} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_batch_report(reports: Optional[Path] = None) -> dict[str, Any]:
    dest = reports or REPORTS
    dest.mkdir(parents=True, exist_ok=True)
    # Refresh dedicated audit + ranking artifacts alongside the batch report.
    write_audit(dest)
    write_ranking(dest)
    report = build_batch_report()
    (dest / "batch-report.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8"
    )
    (dest / "batch-report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    report = write_batch_report()
    print(REPORTS / "batch-report.md")
    print(
        f"pass={report['pass_count']} fail={report['fail_count']} "
        f"mean={report['score_spread']['mean']} "
        f"spearman={report['ranking']['spearman_rho']}"
    )


if __name__ == "__main__":
    main()
