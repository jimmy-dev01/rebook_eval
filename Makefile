# Use a different interpreter with: make clean setup PY=python3.13
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

# Load committed defaults from .env when present (never commit secrets).
ifneq (,$(wildcard .env))
  include .env
  export
endif

.PHONY: env check setup setup-gym test test-gym test-naive run replay grade grade-judge regrade regrade-judge model-compare v7-confusion adversarial-audit policy-ranking batch-report reward-quality docker-build docker-demo docker-down clean

# ------------------------------------------------------------------
# 1) Configure secrets / keys (do this before V7 or Docker)
# ------------------------------------------------------------------
env: .env

.env: .env.example
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example — edit OPENROUTER_API_KEY (and optional REBOOK_JUDGE_MODEL) before V7 / Docker."; \
	else \
		echo ".env already exists"; \
	fi

# ------------------------------------------------------------------
# 2) One-command verify
# ------------------------------------------------------------------
check: setup test

setup: $(BIN)/pytest

# Optional. Only rebook/env/gym_env.py and tests/test_gym_env.py import
# gymnasium; the core env, grader, and Makefile targets above never do.
setup-gym: setup
	$(BIN)/python -m pip install --quiet --disable-pip-version-check -r requirements-gym.txt

$(BIN)/pytest: requirements-dev.txt
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
	touch $@

test: setup
	$(BIN)/python -m pytest

# Runs the gym adapter tests too. Skips them (not fails) if setup-gym
# hasn't been run — see pytest.importorskip in tests/test_gym_env.py.
test-gym: setup-gym
	REBOOK_TEST_GYM=1 $(BIN)/python -m pytest tests/test_gym_env.py -v

test-naive: setup
	$(BIN)/python -m pytest -v tests/test_naive_grader.py

run: setup
	$(BIN)/python -m rebook

replay: setup
	$(BIN)/python -m rebook.env.replay

grade: setup
	$(BIN)/python -m rebook.grader.cli

grade-judge: setup env
	@test -n "$$OPENROUTER_API_KEY" || (echo "Set OPENROUTER_API_KEY in .env (see .env.example), then retry." && exit 1)
	$(BIN)/python -m rebook.grader.cli --judge

regrade: setup
	$(BIN)/python -c "from rebook.grader.regrade import main; main()"

regrade-judge: setup env
	@test -n "$$OPENROUTER_API_KEY" || (echo "Set OPENROUTER_API_KEY in .env (see .env.example), then retry." && exit 1)
	$(BIN)/python -c "from rebook.grader.regrade import main; main()" --judge

# Regrades R01-R06 with V7 under three judge models, then refreshes V7 confusion.
# Requires OPENROUTER_API_KEY in .env; real API calls.
model-compare: setup env
	@test -n "$$OPENROUTER_API_KEY" || (echo "Set OPENROUTER_API_KEY in .env first" && exit 1)
	$(BIN)/python -c "from rebook.grader.regrade import main; main()" --judge --model anthropic/claude-sonnet-5
	$(BIN)/python -c "from rebook.grader.regrade import main; main()" --judge --model anthropic/claude-opus-5.5
	$(BIN)/python -c "from rebook.grader.regrade import main; main()" --judge --model openai/gpt-4o-mini
	$(BIN)/python -c "from rebook.grader.v7_confusion import main; main()"

# Gold recap honesty vs each V7 judge (reads grades-<label>/ or passk-<label>.json).
v7-confusion: setup
	$(BIN)/python -c "from rebook.grader.v7_confusion import main; main()"

# Reward-quality artifacts (no API key).
adversarial-audit: setup
	$(BIN)/python -c "from rebook.grader.adversary_audit import main; main()"

policy-ranking: setup
	$(BIN)/python -c "from rebook.grader.policy_ranking import main; main()"

batch-report: setup
	$(BIN)/python -c "from rebook.grader.batch_report import main; main()"

# Full reward-quality pack: adversarial audit + policy ranking + batch report.
reward-quality: batch-report

# ------------------------------------------------------------------
# Docker — requires .env (keys ingested as build args into evaluator only)
# ------------------------------------------------------------------
docker-build: env
	docker compose build

docker-demo: docker-build
	docker compose up --abort-on-container-exit

docker-down:
	docker compose down --remove-orphans

clean:
	rm -rf $(VENV) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
