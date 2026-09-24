"""Command-line entry point for the trustworthy grader."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rebook.grader.engine import grade_run
from rebook.grader.judge import DEFAULT_MODEL, openrouter_client
from rebook.paths import CLIENT


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade RB01 trajectories")
    parser.add_argument(
        "runs",
        nargs="*",
        type=Path,
        help="run JSON files (defaults to shipped R01–R06)",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="run V7 with OPENROUTER_API_KEY (3 votes per run)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenRouter model for V7 (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print complete JSON grades",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task = load_json(CLIENT / "task.json")
    fixture = load_json(CLIENT / "fixture.json")
    paths = args.runs or sorted((CLIENT / "runs").glob("R0*.json"))

    client = None
    if args.judge:
        client = openrouter_client()
        if client is None:
            raise SystemExit(
                "OPENROUTER_API_KEY is not set. Export it in this terminal, then retry."
            )

    grades = [
        grade_run(
            load_json(path),
            task,
            fixture,
            judge_client=client,
            judge_model=args.model,
        )
        for path in paths
    ]
    if args.json:
        print(json.dumps(grades, indent=2))
        return

    for grade in grades:
        print(
            f"{grade['run_id']}  {grade['result']}  score={grade['score']:.4f}  "
            f"mode={grade['mode']}  failed={grade['failed']}  skipped={grade['skipped']}"
        )
        for result in grade["verifiers"]:
            if result["status"] in {"fail", "error"}:
                print(f"  {result['id']} {result['evidence']}")


if __name__ == "__main__":
    main()
