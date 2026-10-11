# RWP Console

Screens a fund's data room against RWP's five coverage gates and reduces the gate results to a
disposition. Data rooms stay on local disk; everything else (runs, model calls, catalogs, gates, policy)
lives in Supabase Postgres. README.md covers what the app does; CONTRIBUTING.md holds the full gate table,
database workflow and deploy path; e2e/README.md covers Playwright recipes.

## Working loop

- `make db-start` once per boot (local Postgres in Docker), then `make check` before every commit; the
  pre-commit hook runs the same thing. `make e2e` after any change under web/, server.py or sg/.
- When a hook fails, fix the cause and commit again. CI runs every hook regardless.
- `main` takes changes only through a PR that passes **CI OK** and **Migrations OK**. Merge with a merge
  commit: `.git-blame-ignore-revs` names a commit by SHA, and squash or rebase would orphan it.
- A merge to `main` deploys new migrations to the live Supabase project automatically.

## Conventions the code won't tell you

- **Stdlib first.** HTTP, the server and model calls are plain urllib/http.server; the only runtime deps
  are pyyaml and psycopg. A new dependency needs a reason in the PR.
- **Match the house style:** compact functions, one-line comments that give the why, plain-English names
  that analysts would recognise ("disposition", "gate", "data room").
- **Model calls go through `sg/llm.record`**, so every call lands in `model_calls`, failed ones included.
- **Gates and policy are data, not files.** Change them through `sg/gate_store` / `sg/policy_store` (or the
  console); both keep full history, and each run snapshots the gate YAML and policy version it used.
- **`sg/store.py` returns the same dicts the files used to hold**, so the API and frontend never reshape.
  Keep that contract when adding queries.

## Database

- The schema's source of truth is `supabase/schemas/*.sql`. Change it, then generate the migration with
  `npx supabase db schema declarative sync --name <change>`; CI fails on drift between the two.
- Merged migrations are append-only: add a new one to change anything.
- Every new table gets `enable row level security` and no policies (the app connects as owner; the public
  Data API must see nothing). `tests/test_store.py` enforces this.
- Payload columns are `json`, not `jsonb`: jsonb reorders keys, and the console shows gates, answers and
  flags in the order the pipeline wrote them.
- Tests and the e2e fixture build throwaway databases from the migrations on local Postgres and refuse any
  non-local host. Use the `db` fixture in `tests/conftest.py` for anything that touches the database.

## Frontend

- No build step: plain ES modules in web/js, Shoelace vendored in web/vendor. Types come from JSDoc plus
  `web/js/env.d.ts`, checked by `tsc --checkJs`.
- Every Shoelace tag a view renders must be imported in `web/js/components.js`. Lazily defined components
  race the view code on a cold load (blank tabs, crashed views); `tests/js/components.test.js` enforces it.
- Reproduce a UI bug as a Playwright recipe first, then fix it. Every recipe already fails on console
  errors, uncaught exceptions and failed requests.

## Rust or Python

Python is the default and the specification. Rust is an accelerator for a proven hot spot, never the
home of new behaviour.

Reach for Rust only when all of these hold:

1. **Measured, not suspected.** A benchmark shows the function dominating a workload someone actually
   runs. Calibration: the Rust quote matcher is ~3.5× faster (0.05 vs 0.18 ms per quote), which is
   invisible in a screen run (a few dozen quotes beside multi-second model calls) and only pays off in
   bulk work such as re-verifying 170k sampled quotes.
2. **Pure and CPU-bound.** Strings or numbers in, a simple value out. No I/O, database, network, model
   calls, config or logging; those stay in Python where the rest of the system can see them.
3. **Stable.** The logic has settled. Anything still being tuned (gate rules, routing, catalog heuristics)
   stays in Python until it stops changing.

When it qualifies, follow the pattern `rust/verify` set:

- Keep the Python implementation as the reference (`match_quote_py`) and port it line for line, quirks
  included. The Rust module is optional: `sg/dataroom.py` falls back to Python when the build is absent
  or the input is one Rust cannot hold (a lone surrogate).
- Hold the two in parity: run every test case against both, plus a randomized comparison
  (`tests/test_match_quote.py`). `make test-parity` builds the extension and runs it; CI does too.
- Fix a bug in both implementations in the same commit, with a test that fails on the old behaviour.
- Mirror Python semantics deliberately where the languages differ (`\s` matches four separators that
  `char::is_whitespace` skips; Python maps `’` to `'`) and comment each one where it matters, as
  `rust/verify/src/lib.rs` does.
