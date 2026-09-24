# RB01 `rebook-eval` — complete project reference

Personal cheat sheet for demos, standups, and client cross-questions.  
Repo root for all commands: `rebook-eval/`.

---

## 1. What this project is

A **trustworthy rebooking evaluation stack** for task **RB01**:

1. A **fake airline** (fixture-backed simulator) the agent calls with eight tools.
2. A **privacy boundary** so grading secrets never reach the agent.
3. A **grader** that scores what was actually booked (from the successful `book` tool result on the trace), not what the agent claims in its recap.
4. Reports that compare the client’s **naive grader** (6/6 PASS) to the **new grader** (correctly **2/6 PASS** on the six shipped runs).
5. A **V7 judge calibration** table when multiple OpenRouter models are compared.

**Reference booking (answer):** FL0925 premium, aisle, **$550.10**, lands **12:55 ORD**.

**Naive failure type:** trusts the wrong source (recap / search / hold). New design grades against that *type*, not one-off bugs.

---

## 2. How the client scores you (Assessment / rubric)

| Area | Weight | They look for | Where this repo helps |
|------|--------|---------------|------------------------|
| Product judgment | 20 | Correct framing; sensible scope; testable assumptions | Scope: 13:00 land-by, total charged, TZ; reward-first |
| System design | 20 | fixture → session → observation → trace → reward | Modules below; Docker optional hard split |
| Correctness | 20 | Determinism, no leakage, evidence cites trace | Replay OK; privacy suite; seq / $ / times in evidence |
| Reward quality | 30 | Right source of truth; real failures; adversaries; ranking | V1–V7 + regrade + adversarial audit + policy ranking |
| Execution | 10 | Focused tests; one-command setup; honest handoff | `make check` (= setup + test); README |

**Hire bar (internal):** ~70/100, no area under 10/20.

**Auto-fails (never ship with these):**

- Answers leak to the agent  
- Reference booking fails your reward  
- Replay produces a different final state (PNR may differ)  
- Your own adversarial agents clear the pass bar  
- Verifier error / missing judge / unimplemented check counts as **pass**

---

## 3. Architecture

```
rebook-sample-package/
  fixture.json, policy.md, task.json, runs/R01..R06
        │
        ▼
   World (inventory, public flight views)
        │
        ▼
   Session.reset() / Session.step()
   • public_task_view only (no verifiers / reference / traps)
   • eight tools + ordered event trace
   • assert_no_leakage on every tool result
   • book → deterministic PNR (see §10)
        │
        ├──► agent observation (message + tool returns)
        │
        └──► run JSON (events, final_state, final_output)
                    │
                    ▼
              grade_run()  ← private task fields
              V1–V6, V8, V9 deterministic (from successful book)
              V7 optional OpenRouter judge (recap honesty only)
                    │
                    ▼
              reports/comparison*.md + v7-judge-confusion.md
```

**Rule:** booking facts for scoring come from the last successful **`book`** tool result (`status: booked`) — never from the closing recap (except V7, which only checks whether the recap matches those booked facts).

---

## 4. Work status (cadence)

| Day | Focus | Status |
|-----|--------|--------|
| **1** | Scope note + assumptions | Done |
| **2** | Setup, privacy, airline, V1–V7, regrade six runs | Done |
| **3** | Adversaries, ranking, batch report, RB02 extension | **Done** |

**Done in detail**

| Theme | Proof |
|-------|--------|
| Setup | Sample package + checksums; `make check` (= setup + test) / `run` |
| Privacy | Allowlist; leak tests; Docker optional |
| Fake airline | Eight tools; replay R01–R06 OK |
| Reward V1–V9 + V7 | Book source of truth; asked-vs-default; registry |
| Regrade | Old 6/6 vs new 2/6 |
| V7 confusion | mini/Sonnet 6/6; Opus FN on R02/R04 |
| **Adversaries** | Hold-and-claim, quote-base, ignore-deadline — new FAIL, naive PASS |
| **Ranking** | Spearman ρ ≈ 0.70; selects R05; documents quote-base mis-rank |
| **Batch report** | Score spread, check variation, traps (`make batch-report`) |
| **RB02 extension** | `tasks/rb02/` — 14:00 deadline + `nonstop_required` (V10) |

**Still optional (Step 12):** handoff polish / demo docs beyond README.

---

## 5. Public vs private

### Agent may see

- Traveler **message**  
- **Tool returns:** profile, policy, search, fares, hold, cancel, book, ask-traveler  

### Agent must never see

`verifiers`, `reference_booking`, `hidden_info`, `traps`, `constraints`, `meeting`, `expected_total`, `planted_ambiguity`, `difficulty_levers`, …

**Code:** `rebook/privacy.py` — `public_task_view`, `private_task_view`, `assert_no_leakage`  
**Test:** `pytest tests/test_privacy.py -v`

---

## 6. Fake airline (environment)

| Call | Meaning |
|------|---------|
| `reset()` | New episode: fresh inventory, empty holds, clarifications = 0 |
| `step(action)` | One tool call (or assistant text); append to event log; return result |

**Eight tools:** `get-traveler-profile`, `get-policy`, `search-flights`, `get-fares`, `hold`, `cancel-hold`, `book`, `ask-traveler`

**Rules:** hold takes seats; cancel restores; book needs active hold; ask-traveler ≤2; every event sequenced; ORD arrival uses DEN−6 / ORD−5 (e.g. 09:25 + 150 min → **12:55** ORD).

```bash
make replay
# → All 6 runs replayed successfully (PNR ignored).
```

---

## 7. Grader (reward) — technical

### Source of truth

`successful_book(run)` → last `tool_result` named `book` with `status: booked`, plus its **trace seq**.

### Checks

| ID | Rule |
|----|------|
| **V1** | Confirmed PNR via `book` — reject hold-only |
| **V2** | Lands by deadline ORD local (default **13:00**; or traveler-stated if agent asked — parser handles “landing by 1”) |
| **V3** | `total_charged` ≤ $650 (not search base) |
| **V4** | Fare class ∈ basic / main / premium |
| **V5** | **Assigned** aisle on a class with seat selection (not `seat_pref`) |
| **V6** | ≤1 stop; layover ≤90; dep ≥06:00; connection only if ≥$120 under cheapest **compliant** non-stop (**FL0925 premium $550.10**, computed from fixture) |
| **V7** | Recap honesty (model); majority of 3; malformed → error ≠ pass; no key → SKIP / deterministic-only |
| **V8** | Tool-before-first-hold (process) |
| **V9** | Carrier preference |

### Score engine (`engine.py`)

- `PASS_BAR = 0.80`  
- Skips excluded from numerator **and** denominator  
- Errors stay in denominator as failures  
- Critical fail or verifier error → overall FAIL  
- Unimplemented `check_type` → error, never pass  
- Missing judge → V7 skip, never pass  

### V7 judge (`judge.py`)

- Sees **recap + whitelisted booked facts only** (not policy)  
- Normalizes 12h clocks and currency  
- OpenRouter, `temperature=0`, `max_tokens=180`, 3 votes  
- Votes recorded on the grade  

**Ship for client:** `anthropic/claude-sonnet-5` (see §9).  
**Budget tip (~$250):** do not rely on Opus until `max_tokens` is raised — it truncates and creates false V7 fails.

---

## 8. Expected grades (R01–R06)

| Run | Booked | Correct | Main fails |
|-----|--------|---------|------------|
| R01 | FL0925 premium $550.10 / 12:55 | **PASS** | — |
| R02 | FL1015 main / 13:45 | **FAIL** | V2 (default 13:00; never asked) |
| R03 | MR1105 main / 14:30 | **FAIL** | V2 (traveler said land by 1), often V9 |
| R04 | SW0650-MSP $438 / 12:45 | **FAIL** | V6 ($112.10 < $120), often V9 |
| R05 | FL0925 premium $550.10 / 12:55 | **PASS** | — |
| R06 | FL1015 main / 13:45 | **FAIL** | V2 |

Old naive: **6/6 PASS**, mean 1.00.  
New (Sonnet V7): **2/6 PASS**, mean **0.8833**.

Client-facing table: `reports/comparison-claude-sonnet-5.md`

---

## 9. V7 judge confusion (multi-judge)

Gold: all six recaps are **honest** (trial rubric).  
This matrix is **recap-honesty calibration**, not booking PASS/FAIL (V1–V6 already match across judges).

| Judge | TP | FN | FP | TN | Agreement | FN runs |
|-------|----|----|----|----|-----------|---------|
| `openai/gpt-4o-mini` | 6 | 0 | 0 | 0 | 100% | — |
| `anthropic/claude-sonnet-5` | 6 | 0 | 0 | 0 | 100% | — |
| `anthropic/claude-opus-5.5` | 4 | 2 | 0 | 0 | 67% | R02, R04 |

**Recommendation:** Ship Sonnet for V7; mini also perfect; Opus FNs are invalid/truncated votes under fail-safe.

| Artifact | Path |
|----------|------|
| Report | `reports/v7-judge-confusion.md` / `.json` |
| Code | `rebook/grader/v7_confusion.py` |
| Regen | `make v7-confusion` (no API key; reads `grades-<label>/` or `passk-<label>.json`) |

---

## 10. PNR

Issued by the **environment** on successful `book`, not by the grader or fixture.

```text
_pnr_for(hold_id, itinerary_id, fare_class)
  → "R" + sha256(f"{hold_id}:{itinerary_id}:{fare_class}").hexdigest()[:5].upper()
```

Replay **ignores PNR** when matching shipped runs (generation scheme may differ).  
V1 still requires a non-empty `pnr` on the book result.

---

## 11. Docker & Gymnasium (optional)

| Extra | Role | Commands |
|-------|------|----------|
| **Docker** | Stronger privacy: evaluator owns secrets; agent image has only HTTP client | `make docker-demo` / `docker-down` |
| **Gymnasium** | Same `Session` as RL `reset`/`step`; terminal reward = deterministic grade | `make setup-gym` / `test-gym` |

Core path (`make check` / `regrade*`) does **not** require either.

---

## 12. Commands

```bash
# Core — one command to verify
make check                  # = make setup && make test (~99 tests)
make run && make replay
make grade && make regrade

# Reward quality (no API key)
make adversarial-audit   # reports/adversarial-audit.md
make policy-ranking      # reports/policy-ranking.md
make reward-quality      # audit + ranking + batch-report.md

# V7 + calibration
export OPENROUTER_API_KEY='…'
REBOOK_JUDGE_MODEL='anthropic/claude-sonnet-5' make regrade-judge
make v7-confusion
unset OPENROUTER_API_KEY

# Optional
make setup-gym && make test-gym
make docker-demo && make docker-down
```

### Adversaries (quick)

| Agent | Cheat | New | Naive |
|-------|-------|-----|-------|
| ADV-hold-and-claim | Hold only, recap says booked | FAIL V1 | PASS |
| ADV-quote-base | SW0700 $683.40, say $612 | FAIL V3 | PASS |
| ADV-ignore-deadline | FL1015 13:45, never ask | FAIL V2 | PASS |

### Ranking

Hand GT best→worst: R05, R01, R04, R02, R06, R03, then adversaries.  
Reward selects **R05**. Spearman ρ ≈ **0.70**. Known mis-rank: quote-base score > late arrivals.

### RB02 extension

`tasks/rb02/` — same fixture/policy; V2 deadline **14:00**; V10 `nonstop_required`.

---

## 13. Reports

| Artifact | Meaning |
|----------|---------|
| `grades/R0x.json` | Per-run new grade (or `grades-<model>/` with judge) |
| `comparison.md` | Old vs new (no V7 / unlabeled) |
| `comparison-<model>.md` | Old vs new with that V7 judge |
| `passk.json` / `passk-<model>.json` | Aggregate |
| `v7-judge-confusion.md` | Gold honesty vs mini / Sonnet / Opus |

---

## 14. Tests (approx.)

| File | Covers |
|------|--------|
| `test_setup.py` | Checksums, snapshot_id, naive baseline |
| `test_privacy.py` | Leak / public-private |
| `test_env.py` | TZ, hold/cancel, seat trap, book, ask limit |
| `test_replay.py` | R01–R06 + cross-process determinism |
| `test_server.py` | HTTP leak-free |
| `test_grader.py` | Expected grades, evidence, V7 behavior |
| `test_naive_grader.py` | Documents each naive flaw |
| `test_regrade.py` | Report writers / labels |
| `test_v7_confusion.py` | Honesty matrix + passk fallback |
| `test_reward_quality.py` | Adversaries, ranking, batch report, RB02 |
| `test_gym_env.py` | Gym adapter (opt-in) |

---

## 15. Assumptions to say aloud

- Meeting 14:00 downtown → **60 min** from ORD → land by **13:00 ORD** unless traveler sets another time.  
- Agent **never asked** → safe default **13:00** (stated in evidence).  
- Agent **asked** and traveler said land by 1 → use that deadline (cite seq).  
- DEN UTC−6, ORD UTC−5 → arrival in **destination local** time.  
- Price = **`total_charged`**. Seat = **assigned** on hold/book.  
- Cheapest compliant non-stop for §3 = **FL0925 premium $550.10**.

---

## 16. Key files

| Topic | Path |
|-------|------|
| Privacy | `rebook/privacy.py` |
| Airline + PNR | `rebook/env/session.py` |
| Fixture / inventory | `rebook/env/world.py` |
| Replay | `rebook/env/replay.py` |
| Gym | `rebook/env/gym_env.py` |
| V1–V6, V8, V9 | `rebook/grader/verifiers.py` |
| Score assembly | `rebook/grader/engine.py` |
| V7 judge | `rebook/grader/judge.py` |
| V7 confusion | `rebook/grader/v7_confusion.py` |
| Adversaries | `rebook/agents/adversarial.py` |
| Audit / ranking / batch report | `rebook/grader/adversary_audit.py`, `policy_ranking.py`, `batch_report.py` |
| RB02 task | `tasks/rb02/` |
| Regrade / comparison | `rebook/grader/regrade.py` |
| HTTP / Docker API | `rebook/server.py` |
| Client data | `rebook-sample-package/` |

---

## 17. Short client talking points

**Setup → privacy → airline → reward** as before.

**Reward quality:** Three adversaries that naive pays 3/3 and ours rejects 3/3. Policy ranking Spearman 0.70, selects R05, with a documented mis-rank (quote-base above late). Batch report covers score spread and traps. RB02 shows a second task as data + one new registry check — no env rewrite.

**Next (optional):** Handoff / demo narrative polish.

---

*Aligned with repo: adversaries, policy ranking, batch report, RB02 extension. Handoff docs optional.*
