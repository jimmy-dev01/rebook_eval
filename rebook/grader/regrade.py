"""Regrade shipped runs and write old-vs-new comparison artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rebook.baseline import load_naive_grader
from rebook.grader.engine import grade_run
from rebook.grader.judge import DEFAULT_MODEL, openrouter_client
from rebook.paths import CLIENT, ROOT

REPORTS = ROOT / "reports"
GRADES_DIR = REPORTS / "grades"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def model_label(model: str) -> str:
    """Filename tag for a judge model: 'anthropic/claude-sonnet-5' -> 'claude-sonnet-5'.

    Drops the vendor prefix (the part before '/') because it is not needed to
    tell two reports apart, and replaces anything outside [A-Za-z0-9._-] so the
    result is safe as a filename on any platform.
    """
    tail = model.rsplit("/", 1)[-1]
    return "".join(ch if (ch.isalnum() or ch in "._-") else "-" for ch in tail)


def _booking_summary(run: dict) -> str:
    booking = (run.get("final_state") or {}).get("booking")
    if not booking:
        holds = [
            h
            for h in (run.get("final_state") or {}).get("holds") or []
            if h.get("status") == "held"
        ]
        if holds:
            hold = holds[-1]
            return f"hold only {hold.get('itinerary_id')} {hold.get('fare_class')}"
        return "no booking"
    return (
        f"{booking.get('itinerary_id')} {booking.get('fare_class')} "
        f"${booking.get('total_charged'):.2f} lands {booking.get('arr_local')}"
    )


def _fail_reason(grade: dict) -> str:
    """One readable sentence per failed verifier, without repeating id and verdict."""
    failed = {item["id"]: item for item in grade.get("verifiers", []) if item.get("id") in grade.get("failed", [])}
    order = ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9"]
    parts = []
    for vid in order:
        item = failed.get(vid)
        if not item:
            continue
        evidence = item.get("evidence", "")
        label, _, sentence = evidence.partition(": ")
        parts.append(sentence if label in {"FAIL", "ERROR"} and sentence else evidence)
    return " ".join(parts) if parts else "—"


def regrade_shipped(
    *,
    judge: bool = False,
    model: str = DEFAULT_MODEL,
    out_dir: Optional[Path] = None,
    label: Optional[str] = None,
) -> dict:
    """Grade R01–R06, write JSON grades, and an old-vs-new comparison.

    ``label`` is a filesystem-safe tag that keeps one run's outputs from
    overwriting another's: ``comparison-<label>.md`` / ``.json`` and a
    ``grades-<label>/`` folder, instead of the unlabeled ``comparison.md``
    / ``grades/``.

    When the judge runs and no label is given, the judge model supplies one
    (``anthropic/claude-sonnet-5`` -> ``comparison-claude-sonnet-5.md``), so
    grading with a second model can never silently overwrite the first
    model's report. Pass ``label=""`` to force the unlabeled filenames.
    """
    if judge and label is None:
        label = model_label(model)
    reports = Path(out_dir) if out_dir else REPORTS
    suffix = f"-{label}" if label else ""
    grades_dir = reports / f"grades{suffix}"
    grades_dir.mkdir(parents=True, exist_ok=True)

    task = _load(CLIENT / "task.json")
    fixture = _load(CLIENT / "fixture.json")
    naive = load_naive_grader()

    client = None
    if judge:
        client = openrouter_client()
        if client is None:
            raise SystemExit(
                "OPENROUTER_API_KEY is not set. Export it in this terminal, then retry."
            )

    rows = []
    new_grades = []
    for path in sorted((CLIENT / "runs").glob("R0*.json")):
        run = _load(path)
        new = grade_run(run, task, fixture, judge_client=client, judge_model=model)
        old = naive.grade(run, task, fixture)
        (grades_dir / f"{run['run_id']}.json").write_text(
            json.dumps(new, indent=1) + "\n",
            encoding="utf-8",
        )
        new_grades.append(new)
        rows.append(
            {
                "run_id": run["run_id"],
                "booked": _booking_summary(run),
                "old_result": old["result"],
                "old_score": old["score"],
                "old_failed": old.get("failed") or [],
                "new_result": new["result"],
                "new_score": new["score"],
                "new_failed": new.get("failed") or [],
                "new_skipped": new.get("skipped") or [],
                "new_mode": new.get("mode"),
                "why": _fail_reason(new),
            }
        )

    mean = round(sum(g["score"] or 0 for g in new_grades) / len(new_grades), 4)
    comparison = {
        "old": {
            "grader": "naive_grader.py",
            "pass_count": sum(1 for r in rows if r["old_result"] == "PASS"),
            "mean_score": 1.0,
        },
        "new": {
            "grader": "rebook.grader",
            "pass_count": sum(1 for r in rows if r["new_result"] == "PASS"),
            "mean_score": mean,
            "mode": new_grades[0]["mode"] if new_grades else None,
            "judge_model": model if judge else None,
            "label": label,
        },
        "runs": rows,
    }
    (reports / f"comparison{suffix}.json").write_text(
        json.dumps(comparison, indent=1) + "\n",
        encoding="utf-8",
    )
    (reports / f"comparison{suffix}.md").write_text(_markdown(comparison), encoding="utf-8")
    (reports / f"passk{suffix}.json").write_text(
        json.dumps(
            {
                "k": len(new_grades),
                "pass_at_k": any(g["result"] == "PASS" for g in new_grades),
                "mean_score": mean,
                "runs": [
                    {
                        "run_id": g["run_id"],
                        "score": g["score"],
                        "result": g["result"],
                        "failed": g["failed"],
                        "skipped": g["skipped"],
                    }
                    for g in new_grades
                ],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return comparison


def _markdown(comparison: dict) -> str:
    old = comparison["old"]
    new = comparison["new"]
    title = "# Old vs new grader — R01–R06"
    if new.get("judge_model"):
        title += f" (V7 judge: `{new['judge_model']}`)"
    lines = [
        title,
        "",
        f"Old (`naive_grader.py`): **{old['pass_count']}/6 PASS**, mean score {old['mean_score']:.2f}.",
        f"New (`rebook.grader`): **{new['pass_count']}/6 PASS**, mean score {new['mean_score']:.4f}"
        f" ({new['mode']}).",
        "",
        "| Run | Booked | Old | New | New fails | Why |",
        "|-----|--------|-----|-----|-----------|-----|",
    ]
    for row in comparison["runs"]:
        new_failed = ", ".join(row["new_failed"]) or "—"
        why = row["why"].replace("|", "/")
        lines.append(
            f"| {row['run_id']} | {row['booked']} | "
            f"{row['old_result']} {row['old_score']:.2f} | "
            f"{row['new_result']} {row['new_score']:.4f} | {new_failed} | {why} |"
        )
    if new.get("mode") == "full":
        v7_note = (
            f"V7 ran on `{new.get('judge_model') or 'default model'}` (OpenRouter honesty "
            "check). See the Why column above for whether this model's votes changed any "
            "PASS/FAIL relative to the deterministic-only grade."
        )
    else:
        v7_note = (
            "V7 was skipped (no API key); scores are deterministic-only. "
            "Run `make regrade-judge` to include V7."
        )
    lines.extend(
        [
            "",
            "Facts for the new grade come from the successful `book` tool result, not the recap.",
            v7_note,
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Regrade R01–R06 and write comparison")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--label",
        default=None,
        help=(
            "filesystem-safe tag; writes comparison-<label>.md. With --judge and no "
            "--label, the judge model name is used. Pass --label '' for comparison.md."
        ),
    )
    args = parser.parse_args()
    dest = Path(args.out) if args.out else REPORTS
    comparison = regrade_shipped(judge=args.judge, model=args.model, out_dir=dest, label=args.label)
    written = comparison["new"]["label"]
    suffix = f"-{written}" if written else ""
    print(dest / f"comparison{suffix}.md")
    for row in comparison["runs"]:
        print(
            f"{row['run_id']}  old={row['old_result']}  new={row['new_result']}  "
            f"failed={row['new_failed']}  skipped={row['new_skipped']}"
        )
    print(f"mode={comparison['new']['mode']}  mean={comparison['new']['mean_score']}")


if __name__ == "__main__":
    main()
