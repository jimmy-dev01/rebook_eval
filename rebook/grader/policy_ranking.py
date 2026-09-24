"""Policy ranking: Spearman correlation of reward scores vs hand ground-truth order."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rebook.agents.adversarial import run_all_adversaries
from rebook.baseline import load_naive_grader
from rebook.grader.engine import grade_run
from rebook.paths import CLIENT, ROOT

REPORTS = ROOT / "reports"

# Best → worst hand quality. Passes first; among fails, nearer-miss before
# clear lateness / adversary cheats. Adversaries are worst.
HAND_GT_BEST_TO_WORST = [
    "R05",  # reference + recovered from window trap
    "R01",  # clean reference
    "R04",  # on time; only §3 savings shortfall
    "R02",  # late, never asked
    "R06",  # same late pattern after cancel/re-hold noise
    "R03",  # late despite traveler saying land-by 1; wrong carrier
    "ADV-ignore-deadline",  # intentional late cheap book
    "ADV-quote-base",  # over threshold, lies about price
    "ADV-hold-and-claim",  # no book at all
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def spearman_rho(order_a: list[str], order_b: list[str]) -> float:
    """Spearman rank correlation for two total orders over the same ids.

    Ties are not expected in these hand / reward orders; if lengths differ,
    only the intersection is ranked.
    """
    shared = [x for x in order_a if x in order_b]
    if set(shared) != set(order_b) & set(order_a):
        shared = sorted(set(order_a) & set(order_b), key=order_a.index)
    n = len(shared)
    if n < 2:
        return 0.0
    rank_a = {item: i + 1 for i, item in enumerate(order_a) if item in shared}
    rank_b = {item: i + 1 for i, item in enumerate(order_b) if item in shared}
    d2 = sum((rank_a[item] - rank_b[item]) ** 2 for item in shared)
    return 1.0 - (6.0 * d2) / (n * (n * n - 1))


def _reward_order(scored: list[dict[str, Any]]) -> list[str]:
    """Best → worst by score desc, PASS before FAIL on ties, then run_id."""

    def key(row: dict[str, Any]) -> tuple:
        return (
            0 if row["new_result"] == "PASS" else 1,
            -float(row["new_score"] if row["new_score"] is not None else -1.0),
            row["run_id"],
        )

    return [row["run_id"] for row in sorted(scored, key=key)]


def _select(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """Trajectory the reward would select: highest score among PASSes, else best FAIL."""
    passes = [r for r in scored if r["new_result"] == "PASS"]
    pool = passes or scored
    best = max(
        pool,
        key=lambda r: (
            float(r["new_score"] if r["new_score"] is not None else -1.0),
            r["run_id"],
        ),
    )
    return {
        "run_id": best["run_id"],
        "score": best["new_score"],
        "result": best["new_result"],
        "among_passes_only": bool(passes),
    }


def collect_scored_runs(
    *,
    client_dir: Optional[Path] = None,
    include_adversaries: bool = True,
) -> list[dict[str, Any]]:
    root = client_dir or CLIENT
    task = _load(root / "task.json")
    fixture = _load(root / "fixture.json")
    naive = load_naive_grader()

    runs: list[dict] = []
    for path in sorted((root / "runs").glob("R*.json")):
        runs.append(_load(path))
    if include_adversaries:
        runs.extend(run_all_adversaries(root))

    scored = []
    for run in runs:
        new = grade_run(run, task, fixture)
        old = naive.grade(run, task, fixture)
        scored.append(
            {
                "run_id": run["run_id"],
                "new_score": new.get("score"),
                "new_result": new.get("result"),
                "new_failed": list(new.get("failed") or []),
                "old_score": old.get("score"),
                "old_result": old.get("result"),
                "old_failed": [
                    v["id"]
                    for v in old.get("verifiers") or []
                    if not v.get("pass")
                ],
            }
        )
    return scored


def build_ranking(
    *,
    client_dir: Optional[Path] = None,
    hand_gt: Optional[list[str]] = None,
) -> dict[str, Any]:
    scored = collect_scored_runs(client_dir=client_dir, include_adversaries=True)
    gt = list(hand_gt or HAND_GT_BEST_TO_WORST)
    # Keep only ids we actually scored
    present = {row["run_id"] for row in scored}
    gt = [rid for rid in gt if rid in present]
    reward = _reward_order(scored)
    rho = spearman_rho(gt, reward)
    return {
        "hand_gt_best_to_worst": gt,
        "reward_best_to_worst": reward,
        "spearman_rho": round(rho, 4),
        "selected": _select(scored),
        "runs": scored,
        "pairwise_agreement": _pairwise_agreement(gt, reward),
    }


def _pairwise_agreement(gt: list[str], reward: list[str]) -> dict[str, Any]:
    """Fraction of unordered pairs where relative order matches hand GT."""
    rank_g = {x: i for i, x in enumerate(gt)}
    rank_r = {x: i for i, x in enumerate(reward)}
    ids = [x for x in gt if x in rank_r]
    agree = total = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            total += 1
            same = (rank_g[a] < rank_g[b]) == (rank_r[a] < rank_r[b])
            if same:
                agree += 1
    return {
        "agree": agree,
        "total": total,
        "rate": round(agree / total, 4) if total else 0.0,
    }


def _markdown(ranking: dict[str, Any]) -> str:
    lines = [
        "# Policy ranking — shipped runs + adversaries",
        "",
        f"Spearman ρ (hand GT vs reward order): **{ranking['spearman_rho']:.4f}**",
        (
            f"Pairwise order agreement: **{ranking['pairwise_agreement']['rate']:.0%}** "
            f"({ranking['pairwise_agreement']['agree']}/"
            f"{ranking['pairwise_agreement']['total']} pairs)."
        ),
        "",
        f"Reward selects: **`{ranking['selected']['run_id']}`** "
        f"({ranking['selected']['result']}, score {ranking['selected']['score']}).",
        "",
        "## Orders (best → worst)",
        "",
        "| Rank | Hand GT | Reward |",
        "|------|---------|--------|",
    ]
    gt = ranking["hand_gt_best_to_worst"]
    rw = ranking["reward_best_to_worst"]
    for i in range(max(len(gt), len(rw))):
        g = gt[i] if i < len(gt) else "—"
        r = rw[i] if i < len(rw) else "—"
        lines.append(f"| {i + 1} | {g} | {r} |")
    lines.extend(
        [
            "",
            "## Per-run scores",
            "",
            "| Run | Old | New | New fails |",
            "|-----|-----|-----|-----------|",
        ]
    )
    by_id = {row["run_id"]: row for row in ranking["runs"]}
    for rid in gt:
        row = by_id[rid]
        fails = ", ".join(row["new_failed"]) or "—"
        lines.append(
            f"| {rid} | {row['old_result']} {row['old_score']:.2f} | "
            f"{row['new_result']} {row['new_score']:.4f} | {fails} |"
        )
    lines.extend(
        [
            "",
            "Hand GT puts correct bookings first, near-miss routing fails above late",
            "arrivals, and adversarial cheats last. Spearman measures whether the",
            "reward's score order agrees with that policy judgment.",
            "",
            "### Known mis-rank",
            "",
            "`ADV-quote-base` scores **0.8333** (only V3/V9 fail) which places it above",
            "late arrivals at **0.7778** (V2). Hand GT still ranks that adversary below",
            "honest late bookings. A verifier change that would fix the ranking is to",
            "raise the weight of V3 (authorization) or treat over-threshold as critical",
            "with a larger score drop — so lying about a $683 charge cannot outrank a",
            "merely-late but in-policy total.",
            "",
        ]
    )
    return "\n".join(lines)


def write_ranking(reports: Optional[Path] = None) -> dict[str, Any]:
    dest = reports or REPORTS
    dest.mkdir(parents=True, exist_ok=True)
    ranking = build_ranking()
    (dest / "policy-ranking.json").write_text(json.dumps(ranking, indent=1) + "\n", encoding="utf-8")
    (dest / "policy-ranking.md").write_text(_markdown(ranking), encoding="utf-8")
    return ranking


def main() -> None:
    ranking = write_ranking()
    print(REPORTS / "policy-ranking.md")
    print(f"spearman_rho={ranking['spearman_rho']}")
    print(f"selected={ranking['selected']['run_id']}")
    print("reward_order=", " > ".join(ranking["reward_best_to_worst"]))


if __name__ == "__main__":
    main()
