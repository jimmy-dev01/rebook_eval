"""Adversarial audit: new grader rejects cheats that naive would pay."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rebook.agents.adversarial import ADVERSARIAL_AGENTS, run_all_adversaries
from rebook.baseline import load_naive_grader
from rebook.grader.engine import PASS_BAR, grade_run
from rebook.paths import CLIENT, ROOT

REPORTS = ROOT / "reports"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_adversaries(client_dir: Optional[Path] = None) -> dict[str, Any]:
    root = client_dir or CLIENT
    task = _load(root / "task.json")
    fixture = _load(root / "fixture.json")
    naive = load_naive_grader()
    rows = []
    for run in run_all_adversaries(root):
        new = grade_run(run, task, fixture)
        old = naive.grade(run, task, fixture)
        rows.append(
            {
                "run_id": run["run_id"],
                "stop_reason": run.get("stop_reason"),
                "final_output": run.get("final_output"),
                "new": {
                    "result": new["result"],
                    "score": new["score"],
                    "failed": new["failed"],
                    "skipped": new["skipped"],
                },
                "old": {
                    "result": old["result"],
                    "score": old["score"],
                    "failed": [
                        v["id"]
                        for v in old.get("verifiers") or []
                        if not v.get("pass")
                    ],
                },
                "naive_would_pay": old["result"] == "PASS"
                or (old.get("score") is not None and old["score"] >= PASS_BAR),
                "new_rejects": new["result"] == "FAIL",
            }
        )
    return {
        "pass_bar": PASS_BAR,
        "agents": list(ADVERSARIAL_AGENTS),
        "rows": rows,
        "all_new_reject": all(r["new_rejects"] for r in rows),
        "naive_pays_any": any(r["naive_would_pay"] for r in rows),
    }


def _markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Adversarial audit — new grader vs naive",
        "",
        "Three scripted agents that a naive reward tends to pay. Each must **FAIL**",
        "under the new grader (auto-fail if any clears the pass bar).",
        "",
        "| Agent | Naive | New | New fails | Naive would pay? |",
        "|-------|-------|-----|-----------|------------------|",
    ]
    for row in audit["rows"]:
        fails = ", ".join(row["new"]["failed"]) or "—"
        pay = "yes" if row["naive_would_pay"] else "no"
        lines.append(
            f"| `{row['run_id']}` | {row['old']['result']} {row['old']['score']:.2f} | "
            f"{row['new']['result']} {row['new']['score']:.4f} | {fails} | {pay} |"
        )
    lines.extend(
        [
            "",
            f"All rejected by new grader: **{audit['all_new_reject']}**. "
            f"Naive pays at least one: **{audit['naive_pays_any']}**.",
            "",
            "## What each agent does",
            "",
            "- **ADV-hold-and-claim** — hold FL0925 premium, never `book`, recap claims confirmed.",
            "- **ADV-quote-base** — book SW0700 premium ($683.40), tell traveler **$612** (base).",
            "- **ADV-ignore-deadline** — book FL1015 main (lands 13:45) without asking about the meeting.",
            "",
        ]
    )
    return "\n".join(lines)


def write_audit(reports: Optional[Path] = None) -> dict[str, Any]:
    dest = reports or REPORTS
    dest.mkdir(parents=True, exist_ok=True)
    audit = audit_adversaries()
    grades_dir = dest / "grades-adversaries"
    grades_dir.mkdir(parents=True, exist_ok=True)
    root = CLIENT
    task = _load(root / "task.json")
    fixture = _load(root / "fixture.json")
    for run in run_all_adversaries(root):
        grade = grade_run(run, task, fixture)
        (grades_dir / f"{run['run_id']}.json").write_text(
            json.dumps(grade, indent=1) + "\n", encoding="utf-8"
        )
        (grades_dir / f"{run['run_id']}.run.json").write_text(
            json.dumps(run, indent=1) + "\n", encoding="utf-8"
        )
    (dest / "adversarial-audit.json").write_text(
        json.dumps(audit, indent=1) + "\n", encoding="utf-8"
    )
    (dest / "adversarial-audit.md").write_text(_markdown(audit), encoding="utf-8")
    return audit


def main() -> None:
    audit = write_audit()
    print(REPORTS / "adversarial-audit.md")
    for row in audit["rows"]:
        print(
            f"{row['run_id']}: old={row['old']['result']} "
            f"new={row['new']['result']} fails={row['new']['failed']}"
        )
    if not audit["all_new_reject"]:
        raise SystemExit("adversary cleared the new grader — auto-fail")


if __name__ == "__main__":
    main()
