# RB01 rebooking eval

A simulated airline and a grader you can trust for the RB01 flight-rebooking task. An agent rebooks a traveler through the airline's tools, and the grader checks what was actually booked, using the trace and the fixture rather than the agent's own claims.

---

## Quick start

**One command** from this directory (creates `.venv`, installs deps, runs the full suite — about 99 tests):

```bash
make check
```

That is the only command you need to verify the project. Equivalent form: `make setup && make test`.

You need Python 3.9 or later; the stock macOS `python3` works. To use a different interpreter: `make clean check PY=python3.13`.

For demos and cross-questions, see also [PROJECT-REFERENCE.md](PROJECT-REFERENCE.md) (internal notes).

---

## More commands

```
make setup              # creates .venv and installs the pinned test dependencies
make test               # runs the tests (~99)
make test-naive         # lists each flaw in the old grader, one test per flaw
make run                # checks the client's files and prints the old grader's verdicts
make replay             # replays R01–R06 through the env (PNR may differ)
make grade              # runs V1–V6/V8/V9; V7 is an explicit skip
make regrade            # writes reports/grades + old-vs-new comparison (V7 skipped)
make adversarial-audit  # three cheats vs naive
make policy-ranking     # Spearman vs hand GT
make batch-report       # batch summary (also refreshes audit + ranking)
make reward-quality     # full reward-quality pack (= batch-report)
make v7-confusion       # gold honesty vs mini / Sonnet / Opus (no API; needs prior grades)
make model-compare      # three V7 judges + v7-confusion (needs OPENROUTER_API_KEY)
```

Haiku/Opus raw-run comparison (needs sibling `../rebook-trial/gen/runs_raw`):

```bash
.venv/bin/python scripts/compare_all_runs.py
# -> reports/haiku-opus-old-vs-new.md
```

### Run V7 with OpenRouter

Do not paste an API key into source code, `.env`, the README, or Git. Export it
only in the terminal session that runs the judge:

```bash
export OPENROUTER_API_KEY='paste-key-here'
make grade-judge      # print grades with V7
make regrade-judge    # write reports/comparison-<judge-model>.md
unset OPENROUTER_API_KEY
```

When the judge runs, the report filename carries the judge model, so
grading with a second model never overwrites the first one's report:
`REBOOK_JUDGE_MODEL='anthropic/claude-sonnet-5' make regrade-judge` writes
`reports/comparison-claude-sonnet-5.md` (plus `comparison-claude-sonnet-5.json`,
`passk-claude-sonnet-5.json`, and `grades-claude-sonnet-5/`). The unlabeled
`reports/comparison.md` is what `make regrade` (no judge) writes.

V7 uses three votes per run. The default model is `openai/gpt-4o-mini`. The
client-facing recommendation is **`anthropic/claude-sonnet-5`**. To change it:

```bash
export REBOOK_JUDGE_MODEL='anthropic/claude-sonnet-5'
```

Without a key, `make grade` marks V7 `SKIP` and reports
`mode=deterministic-only`; a missing judge never receives pass credit.

### Compare the V7 judge across models

Regrades R01–R06 three times, once per judge model, each to its own
`reports/comparison-<label>.md` (the unlabeled `comparison.md` from
`make regrade-judge` is untouched):

```bash
export OPENROUTER_API_KEY='paste-key-here'
make model-compare
unset OPENROUTER_API_KEY
```

Writes `comparison-claude-sonnet-5.md`, `comparison-claude-opus-5.5.md`, and
`comparison-gpt-4o-mini.md`, then regenerates `v7-judge-confusion.md`
(gold recap honesty vs each judge — no extra API cost). Costs real API calls
for the three regrades — three votes × six runs × three models.

From existing grade / passk artifacts only (no API key):

```bash
make v7-confusion   # -> reports/v7-judge-confusion.md
```

One model by hand, filename chosen for you from the model:

```bash
.venv/bin/python -c "from rebook.grader.regrade import main; main()" \
  --judge --model anthropic/claude-opus-5.5
# -> reports/comparison-claude-opus-5.5.md
```

Add `--label <name>` to pick the suffix yourself, or `--label ''` to write
the unlabeled `comparison.md`.

## Optional: Gymnasium adapter

`rebook/env/gym_env.py` wraps `Session` in a standard `gymnasium.Env`
(`reset()` / `step()`, one action = one tool call, terminal reward = the
deterministic grade). It exists for a future RL training loop; nothing
else in this repo imports it, and `make setup` / `make test` never install
or run it.

```bash
make setup-gym    # installs gymnasium into .venv, on top of make setup
make test-gym     # runs tests/test_gym_env.py
```

See the module docstring in `rebook/env/gym_env.py` for the action/
observation space design and why tool calls are JSON-encoded `Text` rather
than fixed numeric spaces.

## Optional: Docker isolation

`docker-compose.yml` splits the airline into two containers so the privacy
boundary is enforced by the filesystem/network, not just by convention:

- **`evaluator`** — has `rebook-sample-package/` (fixture, task, policy) and
  `rebook/grader`. Serves the eight tools over HTTP (`rebook/server.py`).
  Not published to the host — `expose`, not `ports`, in the compose file —
  only reachable from the `agent` service on the internal network.
- **`agent`** — has exactly one file, `docker/agent_client.py`. No fixture,
  no task, no policy, no grader source ships on this image; the only way it
  can act is the HTTP calls that file makes to `evaluator`.

```bash
make docker-demo   # builds both images, agent plays the reference booking, exits
make docker-down   # tears the compose network down
```

Verify the isolation directly:

```bash
docker run --rm --entrypoint find rebook-eval-agent /app
# -> /app, /app/agent_client.py — nothing else, no fixture/task/policy anywhere on the image
```

`tests/test_server.py` exercises `rebook/server.py` in-process on an
ephemeral port (no Docker needed for CI) and asserts every response is
leak-free using the same `assert_no_leakage` check the in-process tools use
— Docker is the deployment fence, the leakage guarantee itself is unchanged.

## Layout

```
rebook-eval/
├── Makefile                      # make check = setup + test
├── README.md
├── PROJECT-REFERENCE.md          # internal notes (demos / standups)
├── pytest.ini
├── requirements-dev.txt          # pytest (core path)
├── requirements-gym.txt          # optional Gymnasium
├── client-files.sha256           # checksums of the sample package
├── docker-compose.yml
├── docker/
│   ├── Dockerfile.evaluator
│   ├── Dockerfile.agent
│   └── agent_client.py           # only file on the agent image
├── rebook-sample-package/        # client sample — copied unchanged
│   ├── fixture.json
│   ├── policy.md
│   ├── task.json
│   ├── naive_grader.py
│   ├── runs/R01.json … R06.json
│   └── grades/                   # shipped naive grades
├── tasks/
│   └── rb02/                     # data-only second task (14:00 + nonstop)
│       ├── fixture.json
│       ├── policy.md
│       ├── task.json
│       └── README.md
├── scripts/
│   └── compare_all_runs.py       # Haiku/Opus raw-run old vs new table
├── rebook/
│   ├── __main__.py               # make run — naive baseline
│   ├── paths.py
│   ├── privacy.py                # public vs private task views
│   ├── baseline.py               # loads naive_grader.py
│   ├── server.py                 # HTTP tools for Docker evaluator
│   ├── agents/
│   │   ├── adversarial.py        # hold-and-claim, quote-base, ignore-deadline
│   │   └── run_builder.py
│   ├── env/
│   │   ├── world.py              # fixture + inventory
│   │   ├── session.py            # reset / step + eight tools
│   │   ├── replay.py
│   │   ├── timeutil.py
│   │   └── gym_env.py            # optional Gymnasium adapter
│   └── grader/
│       ├── verifiers.py          # V1–V6, V8–V10 (incl. nonstop_required)
│       ├── engine.py             # grade_run, PASS_BAR
│       ├── judge.py              # V7 OpenRouter honesty judge
│       ├── regrade.py            # old vs new comparison
│       ├── v7_confusion.py       # multi-judge honesty matrix
│       ├── adversary_audit.py
│       ├── policy_ranking.py
│       ├── batch_report.py
│       └── private.py            # grader-only task slice
├── tests/                        # pytest suite (~99)
│   ├── test_setup.py
│   ├── test_privacy.py
│   ├── test_env.py
│   ├── test_replay.py
│   ├── test_grader.py
│   ├── test_naive_grader.py
│   ├── test_regrade.py
│   ├── test_server.py
│   ├── test_v7_confusion.py
│   ├── test_reward_quality.py
│   └── test_gym_env.py           # optional; make test-gym
└── reports/                      # Markdown summaries (JSON/grades gitignored)
    ├── README.md
    ├── comparison.md
    ├── comparison-<model>.md
    ├── v7-judge-confusion.md
    ├── adversarial-audit.md
    ├── policy-ranking.md
    ├── batch-report.md
    └── haiku-opus-old-vs-new.md
```

## Status

**Done:** project setup, client files under checksum, naive-grader
baseline, public/private split, **environment with eight tools**, full replay of
R01–R06, the **V1–V7 reward path**, and the **reward-quality pack**:

- Adversarial agents (`ADV-hold-and-claim`, `ADV-quote-base`, `ADV-ignore-deadline`)
  — new grader rejects all three; naive pays all three (`make adversarial-audit`)
- Policy ranking with Spearman ρ vs hand GT (`make policy-ranking`)
- Batch report (`make batch-report` / `make reward-quality`)
- V7 judge calibration across mini / Sonnet / Opus (`make v7-confusion`)
- Extension task **RB02** under `tasks/rb02/` (14:00 land-by + `nonstop_required`)

Deterministic grading passes R01/R05, fails R02/R03/R06 on arrival, and fails
R04 on routing. `make regrade` writes `reports/comparison.md` (old 6/6 PASS vs
new 2/6 PASS). Ship Sonnet for client-facing V7 (`reports/comparison-claude-sonnet-5.md`).

Also done: an optional **Gymnasium adapter** (`make setup-gym test-gym`) for
a future training loop, and an optional **Docker isolation** boundary
(`make docker-demo`) that puts the fixture/task/policy/grader in one
container and the agent's tool client in another with no local access to
any of them — see the two "Optional" sections above. Neither changes
`make check` / `make regrade*`, which remain the core, dependency-free path.

**Still optional:** a short handoff note (assumptions, tradeoffs, limits, what
comes next, and one mistake you caught). The README + `PROJECT-REFERENCE.md`
cover day-to-day use; a dedicated handoff doc is polish for the final demo.
