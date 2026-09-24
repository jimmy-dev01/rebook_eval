# Reports

Human-readable pipeline outputs (Markdown). Regenerate anytime from the
repo root; do not hand-edit.

| File | Command |
|------|---------|
| `comparison.md` | `make regrade` |
| `comparison-<model>.md` | `make regrade-judge` / `make model-compare` |
| `adversarial-audit.md` | `make adversarial-audit` |
| `policy-ranking.md` | `make policy-ranking` |
| `batch-report.md` | `make batch-report` / `make reward-quality` |
| `v7-judge-confusion.md` | `make v7-confusion` |
| `haiku-opus-old-vs-new.md` | `.venv/bin/python scripts/compare_all_runs.py` |

JSON grade dumps and `grades*/` folders are **gitignored** — they rewrite on
every regrade. The Markdown summaries above are what you share with reviewers.
