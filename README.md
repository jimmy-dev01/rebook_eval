# RB01 rebooking eval

A simulated airline and a grader you can trust for the RB01 flight-rebooking task. An agent rebooks a traveler through the airline's tools, and the grader checks what was actually booked, using the trace and the fixture rather than the agent's own claims.

You need Python 3.9 or later; the stock macOS `python3` works.

---

## 1. Configure keys (do this first)

Copy the example env file and fill in values **before** V7 judge commands or Docker:

```bash
make env
# same as: cp .env.example .env
```

Then edit `.env`:

| Variable | Required for | Notes |
|----------|----------------|-------|
| `OPENROUTER_API_KEY` | V7 (`make grade-judge`, `regrade-judge`, `model-compare`) | From [openrouter.ai/keys](https://openrouter.ai/keys). Leave empty for deterministic-only grading. |
| `REBOOK_JUDGE_MODEL` | V7 (optional override) | Default in example: `anthropic/claude-sonnet-5` |

**Never commit `.env`.** It is gitignored. Only `.env.example` is in the repo.

Docker reads the same `.env`: keys are passed into the **evaluator** image as build args and again at container start. The **agent** image never receives them.

---

## 2. Quick start (verify the project)

**One command** (creates `.venv`, installs deps, runs the suite — about 99 tests):

```bash
make check
```

Equivalent: `make setup && make test`.  
Other Python: `make clean check PY=python3.13`.

No API key is required for `make check`.

---

## 3. Core local commands

```
make setup              # creates .venv and installs pinned test dependencies
make test               # runs the tests (~99)
make test-naive         # lists each flaw in the old grader, one test per flaw
make run                # checks the client's files and prints the old grader's verdicts
make replay             # replays R01–R06 through the env (PNR may differ)
make grade              # V1–V6/V8/V9; V7 skipped (deterministic-only)
make regrade            # reports/grades + old-vs-new comparison (V7 skipped)
make adversarial-audit  # three cheats vs naive
make policy-ranking     # Spearman vs hand GT
make batch-report       # batch summary (also refreshes audit + ranking)
make reward-quality     # full reward-quality pack (= batch-report)
make v7-confusion       # gold honesty vs prior judge grades (no API)
```

Haiku/Opus raw-run table (needs sibling `../rebook-trial/gen/runs_raw`):

```bash
.venv/bin/python scripts/compare_all_runs.py
# -> reports/haiku-opus-old-vs-new.md
```

---

## 4. V7 honesty judge (uses `.env`)

Ensure `.env` has a real `OPENROUTER_API_KEY` (step 1). Then:

```bash
make grade-judge      # print grades with V7
make regrade-judge    # write reports/comparison-<judge-model>.md
make model-compare    # Sonnet + Opus + mini, then v7-confusion
```

Without a key, `make grade` / `make regrade` mark V7 `SKIP` (`mode=deterministic-only`); a missing judge never counts as a pass.

When the judge runs, filenames include the model so runs do not overwrite each other, e.g. `REBOOK_JUDGE_MODEL` → `reports/comparison-claude-sonnet-5.md`. The unlabeled `reports/comparison.md` is from `make regrade` (no judge).

V7 uses three votes per run. Ship **`anthropic/claude-sonnet-5`** for client-facing demos; `openai/gpt-4o-mini` is a cheaper alternative (set in `.env`).

One-off model:

```bash
.venv/bin/python -c "from rebook.grader.regrade import main; main()" \
  --judge --model anthropic/claude-opus-5.5
```

---

## 5. Optional: Gymnasium adapter

`rebook/env/gym_env.py` wraps `Session` as a `gymnasium.Env` for a future RL loop. Core `make check` does not install or run it.

```bash
make setup-gym    # installs gymnasium into .venv
make test-gym     # runs tests/test_gym_env.py
```

---

## 6. Optional: Docker isolation (after `.env`)

Requires step 1 (`make env` / a `.env` file). Compose **builds the evaluator with your keys** (`OPENROUTER_API_KEY`, `REBOOK_JUDGE_MODEL` as build args + runtime env). The agent container still has **no** keys, fixture, task, or grader — only HTTP to the evaluator.

```bash
make docker-demo   # builds both images (keys → evaluator), runs reference booking, exits
make docker-down   # tear down
```

Verify the agent image stays empty of secrets/data:

```bash
docker run --rm --entrypoint find rebook-eval-agent /app
# -> /app, /app/agent_client.py only
```

`tests/test_server.py` checks the HTTP boundary in-process (no Docker required for CI).

---

## Layout

```
rebook-eval/
├── Makefile                      # make env → make check → … → make docker-demo
├── README.md
├── .env.example                  # copy to .env (gitignored) — keys live here
├── pytest.ini
├── requirements-dev.txt
├── requirements-gym.txt
├── client-files.sha256
├── docker-compose.yml            # passes .env into evaluator build + runtime
├── docker/
│   ├── Dockerfile.evaluator      # ARG/ENV for OpenRouter keys
│   ├── Dockerfile.agent          # no keys, one client file
│   └── agent_client.py
├── rebook-sample-package/        # client sample — unchanged
├── tasks/rb02/                   # data-only second task
├── scripts/compare_all_runs.py
├── rebook/                       # env / grader / agents / server
├── tests/
└── reports/                      # gitignored — regenerated by make regrade / reward-quality / …
```

---

## Status

**Done:** setup under checksum, privacy split, eight-tool airline, R01–R06 replay, V1–V7 reward, reward-quality pack (adversaries, ranking, batch report), RB02 data-only extension, optional Gym + Docker.

Deterministic grading: R01/R05 PASS; R02/R03/R06 FAIL (time); R04 FAIL (routing). Naive 6/6 → new 2/6 (`reports/comparison.md`). Ship Sonnet for V7 (`reports/comparison-claude-sonnet-5.md`).

**Still optional:** short handoff note (assumptions, tradeoffs, one mistake you caught).
