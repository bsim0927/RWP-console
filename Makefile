# The software factory's single source of truth. Pre-commit hooks and GitHub CI call these same
# targets (or the same tool + config), so a green commit locally means a green CI run.
#
#   make setup     install everything, including git hooks
#   make check     everything CI runs except e2e and the database replay
#   make ci        everything CI runs (needs Docker for db-replay)
#   make help      list targets

SHELL := bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help
export PATH := $(HOME)/.cargo/bin:$(HOME)/.local/bin:$(PATH)

UV    := uv run --frozen
NPX   := npx --no-install
CARGO := cargo --quiet
CRATE := --manifest-path rust/verify/Cargo.toml

.PHONY: help setup hooks check ci fix \
        lint lint-py lint-js lint-rust typecheck typecheck-py typecheck-js \
        test test-py test-js test-rust test-parity coverage e2e e2e-smoke \
        migrations db-start db-replay db-stop clean

help: ## list targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------- setup ----------
setup: ## install Python, Node, browser and Rust tooling, then git hooks
	uv sync --frozen
	npm ci
	$(NPX) playwright install chromium
	-rustup component add rustfmt clippy
	$(MAKE) hooks

hooks: ## install the pre-commit and pre-push git hooks
	$(UV) pre-commit install --install-hooks --hook-type pre-commit --hook-type pre-push

# ---------- aggregates ----------
check: lint typecheck test migrations ## fast gate: lint, types, unit tests, migration hygiene
ci: check test-parity e2e db-replay ## full gate, as GitHub runs it

fix: ## apply every autofixer
	$(UV) ruff check --fix .
	$(UV) ruff format .
	$(NPX) eslint --fix .
	$(CARGO) fmt $(CRATE)

# ---------- lint ----------
lint: lint-py lint-js lint-rust ## all linters
lint-py: ## ruff lint + format check
	$(UV) ruff check .
	$(UV) ruff format --check .
lint-js: ## eslint
	$(NPX) eslint --max-warnings=0 .
lint-rust: ## rustfmt check + clippy, warnings are errors
	$(CARGO) fmt $(CRATE) --check
	$(CARGO) clippy $(CRATE) --all-targets -- -D warnings

# ---------- type checks ----------
typecheck: typecheck-py typecheck-js ## all type checkers
typecheck-py: ## mypy
	$(UV) mypy
typecheck-js: ## tsc --checkJs over web/js (no build, no emit)
	$(NPX) tsc -p jsconfig.json

# ---------- tests ----------
test: test-py test-js test-rust ## all unit tests
test-py: ## pytest (runs the unittest suites)
	$(UV) pytest -q
test-js: ## vitest
	$(NPX) vitest run
test-rust: ## cargo test
	$(CARGO) test $(CRATE)
test-parity: ## build the Rust quote matcher and hold it to the Python one
	$(CARGO) build $(CRATE) --release
	cp rust/verify/target/release/lib_verify.so sg/_verify.abi3.so
	$(UV) python -c "from sg import dataroom; assert dataroom.match_quote_rs, 'Rust build not importable'"
	$(UV) pytest -q tests/test_match_quote.py
coverage: ## Python and JS coverage reports (coverage/)
	$(UV) pytest -q --cov --cov-report=term --cov-report=xml:coverage/python.xml
	$(NPX) vitest run --coverage

# ---------- browser recipes ----------
e2e: ## Playwright recipes, desktop + mobile, against a synthetic workspace
	$(NPX) playwright test
e2e-smoke: ## only the @smoke recipes (also used against Vercel previews)
	$(NPX) playwright test --grep @smoke --project=desktop

# ---------- database (Supabase) ----------
migrations: ## static migration hygiene (BASE=origin/main also checks append-only + ordering)
	scripts/check-migrations.sh $(BASE)
db-start: ## start a local Postgres via the Supabase CLI (needs Docker)
	$(NPX) supabase db start
db-replay: db-start ## apply every migration from scratch, lint, and fail on schema drift
	$(NPX) supabase db reset --local
	$(NPX) supabase db lint --local --level warning --fail-on error
	scripts/check-schema-drift.sh
db-stop: ## stop the local Supabase stack
	$(NPX) supabase stop --no-backup

clean: ## remove caches and test output
	rm -rf .pytest_cache .mypy_cache .ruff_cache coverage e2e/.workspace e2e/.results e2e/.report
