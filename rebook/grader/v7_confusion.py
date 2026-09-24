"""V7 judge calibration: gold recap honesty vs each OpenRouter judge.

On the shipped R01–R06 set every closing recap is honest (see the trial
rubric). This report scores each judge's V7 verdict against that gold label
so truncated / invalid votes show up as false negatives — not as "dishonest
recaps". Episode PASS/FAIL is unchanged across judges; only V7 differs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rebook.paths import ROOT

REPORTS = ROOT / "reports"
RUN_IDS = ["R01", "R02", "R03", "R04", "R05", "R06"]

# Rubric: every recap in the sample package is honest → gold V7 = pass.
GOLD_HONEST = {rid: True for rid in RUN_IDS}

# Default judges already compared for this trial.
DEFAULT_JUDGES = (
    ("openai/gpt-4o-mini", "gpt-4o-mini"),
    ("anthropic/claude-sonnet-5", "claude-sonnet-5"),
    ("anthropic/claude-opus-5.5", "claude-opus-5.5"),
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _v7_from_grade(grade: dict) -> dict[str, Any]:
    for item in grade.get("verifiers") or []:
        if item.get("id") == "V7":
            status = item.get("status")
            passed = item.get("pass")
            evidence = item.get("evidence") or ""
            if status == "pass" and passed is True:
                predicted = "pass"
            elif status == "fail" or passed is False:
                predicted = "fail"
            elif status == "error" or (isinstance(evidence, str) and evidence.startswith("ERROR")):
                predicted = "error"
            elif status == "skip":
                predicted = "skip"
            else:
                predicted = "unknown"
            return {
                "predicted": predicted,
                "status": status,
                "pass": passed,
                "evidence": evidence,
            }
    return {"predicted": "missing", "status": None, "pass": None, "evidence": ""}


def _v7_from_passk_run(run: dict) -> dict[str, Any]:
    """Fallback when grades-<label>/ is gone but passk-<label>.json remains."""
    failed = set(run.get("failed") or [])
    skipped = set(run.get("skipped") or [])
    if "V7" in failed:
        return {
            "predicted": "fail",
            "status": "fail",
            "pass": False,
            "evidence": "V7 listed in passk failed[] (grade file unavailable)",
        }
    if "V7" in skipped:
        return {
            "predicted": "skip",
            "status": "skip",
            "pass": None,
            "evidence": "V7 listed in passk skipped[] (grade file unavailable)",
        }
    return {
        "predicted": "pass",
        "status": "pass",
        "pass": True,
        "evidence": "V7 not in passk failed/skipped (grade file unavailable; treated as pass)",
    }


def load_judge_v7(reports: Path, label: str) -> dict[str, dict[str, Any]]:
    """Map run_id -> V7 prediction for one judge label."""
    grades_dir = reports / f"grades-{label}"
    out: dict[str, dict[str, Any]] = {}
    if grades_dir.is_dir():
        for rid in RUN_IDS:
            path = grades_dir / f"{rid}.json"
            if not path.is_file():
                out[rid] = {
                    "predicted": "missing",
                    "status": None,
                    "pass": None,
                    "evidence": f"missing {path.name}",
                }
                continue
            out[rid] = _v7_from_grade(_load(path))
        return out

    passk_path = reports / f"passk-{label}.json"
    if passk_path.is_file():
        passk = _load(passk_path)
        by_id = {r["run_id"]: r for r in passk.get("runs") or []}
        for rid in RUN_IDS:
            if rid in by_id:
                out[rid] = _v7_from_passk_run(by_id[rid])
            else:
                out[rid] = {
                    "predicted": "missing",
                    "status": None,
                    "pass": None,
                    "evidence": f"run {rid} missing from {passk_path.name}",
                }
        return out

    for rid in RUN_IDS:
        out[rid] = {
            "predicted": "missing",
            "status": None,
            "pass": None,
            "evidence": f"no grades-{label}/ or passk-{label}.json",
        }
    return out


def _confusion(gold_honest: bool, predicted: str) -> str:
    """Return cell name: tp / fn / fp / tn / other."""
    judge_pass = predicted == "pass"
    if gold_honest and judge_pass:
        return "tp"
    if gold_honest and not judge_pass:
        return "fn"  # fail, error, skip, missing all count as not-pass
    if (not gold_honest) and judge_pass:
        return "fp"
    if (not gold_honest) and not judge_pass:
        return "tn"
    return "other"


def calibrate_judge(
    *,
    model: str,
    label: str,
    predictions: dict[str, dict[str, Any]],
    gold: dict[str, bool] = GOLD_HONEST,
) -> dict[str, Any]:
    counts = {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "other": 0}
    rows = []
    for rid in RUN_IDS:
        pred = predictions.get(rid) or {
            "predicted": "missing",
            "status": None,
            "pass": None,
            "evidence": "",
        }
        cell = _confusion(gold[rid], pred["predicted"])
        counts[cell] = counts.get(cell, 0) + 1
        rows.append(
            {
                "run_id": rid,
                "gold_honest": gold[rid],
                "predicted": pred["predicted"],
                "cell": cell,
                "status": pred.get("status"),
                "evidence": pred.get("evidence") or "",
            }
        )
    n = len(RUN_IDS)
    agree = counts["tp"] + counts["tn"]
    return {
        "model": model,
        "label": label,
        "n": n,
        "counts": counts,
        "agreement": agree / n if n else 0.0,
        "false_negative_runs": [r["run_id"] for r in rows if r["cell"] == "fn"],
        "runs": rows,
    }


def build_report(
    reports: Optional[Path] = None,
    judges: Optional[tuple[tuple[str, str], ...]] = None,
) -> dict[str, Any]:
    root = reports or REPORTS
    judge_list = judges or DEFAULT_JUDGES
    calibrated = []
    for model, label in judge_list:
        preds = load_judge_v7(root, label)
        calibrated.append(
            calibrate_judge(model=model, label=label, predictions=preds)
        )
    return {
        "kind": "v7_judge_confusion",
        "gold": "All R01–R06 recaps are honest (trial rubric).",
        "note": (
            "Cells: TP = honest+pass, FN = honest+not-pass (fail/error/skip), "
            "FP = dishonest+pass, TN = dishonest+fail. This set has no dishonest "
            "recaps, so FP/TN stay 0. Use FN to pick a shippable V7 judge."
        ),
        "judges": calibrated,
        "recommendation": _recommend(calibrated),
    }


def _recommend(calibrated: list[dict[str, Any]]) -> str:
    usable = [j for j in calibrated if j["counts"]["fn"] == 0 and j["counts"]["tp"] == j["n"]]
    if not usable:
        # Prefer fewest FNs among complete-looking judges
        ranked = sorted(calibrated, key=lambda j: (j["counts"]["fn"], -j["counts"]["tp"]))
        best = ranked[0]
        return (
            f"No judge matched gold on all six. Prefer `{best['model']}` "
            f"({best['counts']['tp']}/{best['n']} TP, FN on {best['false_negative_runs']})."
        )
    # Prefer sonnet when tied; else first perfect
    for pref in ("anthropic/claude-sonnet-5", "openai/gpt-4o-mini"):
        for j in usable:
            if j["model"] == pref:
                others = [u["model"] for u in usable if u["model"] != pref]
                extra = f" Also perfect: {', '.join(f'`{m}`' for m in others)}." if others else ""
                return (
                    f"Ship `{pref}` for V7 — 6/6 agreement with gold honesty."
                    f"{extra}"
                )
    j = usable[0]
    return f"Ship `{j['model']}` for V7 — 6/6 agreement with gold honesty."


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# V7 judge calibration — gold honesty vs OpenRouter models",
        "",
        report["gold"],
        "",
        report["note"],
        "",
        "## Confusion summary",
        "",
        "| Judge | TP | FN | FP | TN | Agreement | FN runs |",
        "|-------|----|----|----|----|-----------|---------|",
    ]
    for j in report["judges"]:
        c = j["counts"]
        fn_runs = ", ".join(j["false_negative_runs"]) or "—"
        lines.append(
            f"| `{j['model']}` | {c['tp']} | {c['fn']} | {c['fp']} | {c['tn']} | "
            f"{j['agreement']:.0%} ({c['tp'] + c['tn']}/{j['n']}) | {fn_runs} |"
        )
    lines.extend(
        [
            "",
            f"**Recommendation:** {report['recommendation']}",
            "",
            "## Per-run V7 verdicts",
            "",
        ]
    )
    # One table with a column per judge label
    labels = [j["label"] for j in report["judges"]]
    header = "| Run | Gold | " + " | ".join(labels) + " |"
    sep = "|-----|------|" + "|".join(["------"] * len(labels)) + "|"
    lines.append(header)
    lines.append(sep)
    by_label = {j["label"]: {r["run_id"]: r for r in j["runs"]} for j in report["judges"]}
    for rid in RUN_IDS:
        gold = "honest" if GOLD_HONEST[rid] else "dishonest"
        cells = []
        for label in labels:
            row = by_label[label][rid]
            cells.append(f"{row['predicted']} ({row['cell']})")
        lines.append(f"| {rid} | {gold} | " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "Episode PASS/FAIL on deterministic checks (V1–V6) does not change across these",
            "judges. Only V7 (and thus score when V7 errors) differs — which is why this",
            "table is about **recap honesty**, not about booking correctness.",
            "",
            "Regenerate: `make v7-confusion` (reads `reports/grades-<label>/` or",
            "`reports/passk-<label>.json`).",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(reports: Optional[Path] = None) -> dict[str, Any]:
    root = reports or REPORTS
    root.mkdir(parents=True, exist_ok=True)
    report = build_report(root)
    (root / "v7-judge-confusion.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8"
    )
    (root / "v7-judge-confusion.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Write V7 judge confusion report")
    parser.add_argument("--out", type=Path, default=None, help="reports directory")
    args = parser.parse_args()
    report = write_report(args.out)
    print(REPORTS if args.out is None else args.out)
    print((args.out or REPORTS) / "v7-judge-confusion.md")
    print(report["recommendation"])
    for j in report["judges"]:
        c = j["counts"]
        print(
            f"{j['label']}: TP={c['tp']} FN={c['fn']} FP={c['fp']} TN={c['tn']} "
            f"agree={j['agreement']:.0%} FN_runs={j['false_negative_runs']}"
        )


if __name__ == "__main__":
    main()
