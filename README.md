# RWP Console (prototype)
Local only. `python3 screen.py <folder with _index/pages.jsonl> [--extractor claude] [--judge claude|jev]`

Flow: retrieve pages -> extract cited facts -> verify every quote is on its cited page -> judge typed
questions -> derive gate result by rule -> reduce to a disposition (the policy) -> save the run to the database.

Data rooms stay local (the data root). Everything else, runs, model calls, catalogs, gates and policy, lives in
Supabase Postgres (DATABASE_URL in .env). Change a gate in the console's Gates and policy view; every edit is
versioned. Keys live in .env (ANTHROPIC_API_KEY, JEV_API_KEY); run ./setup-keys.sh to set them.

Console: `python3 server.py [data-root]` -> http://127.0.0.1:8765 (`PORT=` to change). Overview, screening queue,
per-fund screen/catalog/files/search/history/report, catalogs, file browser, document search, analytics, logs,
gates and policy. Read-only except Run screen and Rebuild catalog. The previous single-page viewer is at /legacy.

Web UI is plain ES modules in web/js, no build step. Components are Shoelace 2.20 (MIT), vendored in web/vendor
with Inter and JetBrains Mono, so the page makes no external requests.

Tests: `make check` runs linters, type checks and unit tests; `make e2e` runs the Playwright recipes.
Run `make setup` once to install the tooling and git hooks. See CONTRIBUTING.md for every quality gate and
how pre-commit and CI mirror each other. Quote verification has an optional Rust build: `./build-rust.sh`
compiles rust/verify into sg/_verify.abi3.so and runs the tests against both implementations. Without it,
sg/dataroom.py uses the Python one.
