# Contributing

## Setup

Needs [uv](https://docs.astral.sh/uv/), Node 22 (`.nvmrc`), and optionally Rust (rustup.rs) and Docker
(for the database checks).

    make setup      # Python + Node deps, Playwright's Chromium, rustfmt/clippy, git hooks
    make help       # every target

## The quality gates

`make` is the single source of truth. Pre-commit hooks and GitHub CI run the same targets from the same
lockfiles (`uv.lock`, `package-lock.json`), so a commit that passes locally passes in CI.

| Gate | Local command | Pre-commit | CI job |
|---|---|---|---|
| Python lint + format (ruff) | `make lint-py` | on commit | CI / Backend |
| Python types (mypy) | `make typecheck-py` | on commit | CI / Backend |
| Backend tests (pytest, py3.12 + 3.14) | `make test-py` | on commit | CI / Backend |
| Frontend lint (eslint) | `make lint-js` | on commit | CI / Frontend |
| Frontend types (`tsc --checkJs`, no build) | `make typecheck-js` | on commit | CI / Frontend |
| Frontend tests (vitest) | `make test-js` | on commit | CI / Frontend |
| Rust fmt + clippy + tests, Python parity | `make lint-rust test-rust test-parity` | on commit (rust/) | CI / Rust |
| Playwright recipes (desktop + mobile) | `make e2e` | on push (desktop) | CI / Playwright |
| Migration hygiene | `make migrations BASE=origin/main` | on commit (supabase/) | Migrations / Naming |
| Migration replay, lint, schema drift | `make db-replay` (Docker) | – | Migrations / Replay |
| Secrets, whitespace, YAML, workflows, shell | `uv run pre-commit run --all-files` | on commit | CI / Repo hygiene |

`make check` runs everything except the browser and database gates; `make fix` applies every autofixer.

Branch protection on `main` should require two checks: **CI OK** and **Migrations OK**. Each one
aggregates its workflow's jobs, so adding a job never means editing the protection rule.

Bypass a hook only in an emergency (`SKIP=mypy git commit ...`); CI still runs it.

## Frontend bugs: Playwright recipes

See [e2e/README.md](e2e/README.md). Every recipe fails on any console error, uncaught exception,
failed request or API error, even when its own assertions pass. Reproduce a UI bug as a recipe first,
then fix it.

## Database (Supabase)

The data rooms stay on local disk. Everything else lives in Postgres: `runs` and `run_gates` (each gate
record plus the exact gate YAML it ran with), `model_calls`, `catalogs` and `catalog_documents`, `gates`
and `gate_history`, and `policies` (newest row in force). Every table has row-level security on and no
policies, so Supabase's public Data API sees nothing; the app connects to Postgres directly.

- **Gates and policy** are edited in the console (Gates and policy view). Both are versioned: every gate edit
  keeps the prior state in `gate_history`, every policy save adds a row to `policies`, and each run records
  the gate definitions and policy version it ran under.
- **The app** uses `DATABASE_URL` from `.env`: the project's session pooler URL, from the dashboard's
  Connect button, with the database password and `?sslmode=require`.
- **Tests and Playwright** never use `.env`'s database. They build throwaway databases from
  `supabase/migrations` on a local Postgres (`make db-start`, Docker) and refuse any non-local host.
  CI uses a Postgres 17 service container instead.
- **Declarative schema** in `supabase/schemas/*.sql` is the source of truth for the tables. Change it,
  then generate the migration: `npx supabase db schema declarative sync --name <describe_change>`.
- Migrations are append-only once merged. Never edit, rename or delete one on `main`; add another.
- CI replays every migration on an empty Postgres, runs `supabase db lint`, fails on drift between
  migrations and `supabase/schemas`, and resets twice to catch non-repeatable migrations. A nightly job
  checks the live project has exactly `main`'s migrations and no schema changes made outside them.
- The pre-database files (`runs/`, `catalog/`) can be imported once with
  `uv run python scripts/import_local_state.py --yes` (dry run without `--yes`).
- Pipeline statuses and owners from the old `PIPELINE.md` are imported once with
  `uv run python scripts/import_pipeline_md.py <PIPELINE.md> <data-root> --yes` (dry run without `--yes`).
  After that the console reads no Markdown from the Drive; statuses move only in the console, by the CIO.

## Deployment (Vercel), planned

Not deployable yet: `server.py` is a long-running local process that reads data rooms from disk.
Runs, catalogs and configuration are already in Postgres; moving to Vercel still means serverless API
routes and data rooms in Supabase Storage. What is already in place:

- `.github/workflows/preview-smoke.yml` runs the `@smoke` recipes against every Vercel preview
  deployment as soon as Vercel's GitHub integration is connected (`E2E_BASE_URL`).
- For protected previews, add a Vercel "Protection Bypass for Automation" secret as the repo secret
  `VERCEL_AUTOMATION_BYPASS_SECRET`.
- Keep secrets in Vercel's and GitHub's secret stores, never in the repo; gitleaks runs on every commit.
