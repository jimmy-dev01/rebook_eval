"""Old vs new grader on Haiku/Opus raw runs. Writes reports/haiku-opus-old-vs-new.md.

From rebook-eval/:

  export OPENROUTER_API_KEY='...'   # optional; without it V7 is SKIP
  .venv/bin/python scripts/compare_all_runs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow `python scripts/compare_all_runs.py` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rebook.baseline import load_naive_grader
from rebook.grader.engine import grade_run
from rebook.grader.judge import openrouter_client
from rebook.paths import CLIENT, ROOT


def main() -> None:
    raw = ROOT.parent / "rebook-trial" / "gen" / "runs_raw"
    paths = sorted(raw.glob("hk*.json")) + sorted(raw.glob("op*.json"))
    if not paths:
        raise SystemExit(f"No hk*/op* runs under {raw}")

    task = json.loads((CLIENT / "task.json").read_text(encoding="utf-8"))
    fixture = json.loads((CLIENT / "fixture.json").read_text(encoding="utf-8"))
    old_g = load_naive_grader()
    judge = openrouter_client()

    lines = [
        "# Old vs new — Haiku/Opus raw runs",
        "",
        f"New V7: {'full (judge on)' if judge else 'SKIP (no OPENROUTER_API_KEY)'}.",
        "Old V7: missing judge counts as **PASS**.",
        "",
        "| Run | Old | New | New fails | New skipped |",
        "|-----|-----|-----|-----------|-------------|",
    ]
    old_pass = new_pass = 0
    for path in paths:
        run = json.loads(path.read_text(encoding="utf-8"))
        old = old_g.grade(run, task, fixture)
        new = grade_run(run, task, fixture, judge_client=judge)
        old_pass += old["result"] == "PASS"
        new_pass += new["result"] == "PASS"
        fails = ",".join(new.get("failed") or []) or "-"
        skips = ",".join(new.get("skipped") or []) or "-"
        lines.append(
            f"| {run.get('run_id', path.stem)} | {old['result']} {old['score']:.2f} | "
            f"{new['result']} {new['score']:.4f} | {fails} | {skips} |"
        )

    n = len(paths)
    lines += [
        "",
        f"Old PASS: **{old_pass}/{n}**. New PASS: **{new_pass}/{n}**.",
        "",
    ]
    out = ROOT / "reports" / "haiku-opus-old-vs-new.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    print(f"old {old_pass}/{n}  new {new_pass}/{n}")


if __name__ == "__main__":
    main()
