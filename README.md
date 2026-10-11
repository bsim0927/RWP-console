# RWP Console

Screens alternative-investment funds for RWP's Manager Coverage Process. Point it at a fund's data room
and it runs the five screening gates (investor eligibility, total annual cost, operability, track record,
disclosure history), then combines the gate results into a disposition such as "Coverable, subject to
conditions" or "Under review".

Every finding is cited: a model extracts facts with verbatim quotes, code checks each quote really appears
on its cited page, a judge answers typed questions as probabilities, and fixed rules (not the model) decide
the result. Low-confidence answers go to an analyst.

## How a screen works

1. **Retrieve**: pick the pages each gate should read, using the document catalog (document types and
   sections), or keywords when no section matches.
2. **Extract**: a model returns cited facts: value, verbatim quote, file, page.
3. **Verify**: every quote is checked against its page; quotes that are not there are rejected.
4. **Judge**: a model answers the gate's typed questions as probabilities.
5. **Derive**: the gate's rules turn the answers into Pass, Fail, Incomplete or Route with disclosure.
6. **Reduce**: the disposition policy combines the gate results into one disposition.

## Where things live

| What | Where |
|---|---|
| Data rooms (PDFs and `_index/pages.jsonl`) | Local disk, the data root (default `~/Desktop/RWP`) |
| Runs, model calls, document catalogs | Supabase Postgres |
| Intake, analyst reviews and checks, confirmed dispositions, screen notes | Supabase Postgres, every change kept |
| Each fund's pipeline status, moved only by the CIO | Supabase Postgres (`fund_status`), every move kept |
| Gates and disposition policy | Supabase Postgres, edited and versioned in the console |
| API keys and the database URL | `.env` (never committed) |

## Running it

Needs [uv](https://docs.astral.sh/uv/), Node 22, and `.env` with `ANTHROPIC_API_KEY`, `JEV_API_KEY`
(`./setup-keys.sh` sets them) and `DATABASE_URL` (see CONTRIBUTING.md).

    make setup                                    # once: tooling and git hooks
    uv run python server.py [data-root]           # the console, at http://127.0.0.1:8765 (PORT= to change)
    uv run python screen.py <data-room-folder>    # screen one data room from the command line

The console covers the overview, the screening queue, each fund (screen, catalog, files, search, history,
note, report), catalogs, a file browser, document search, analytics, the agent monitor, and gates and policy.
It changes data when you run a screen, rebuild a catalog, edit a gate, the policy or the reviewers, save a
fund's intake, review a gate, confirm a disposition, or draft or edit a screen note. The previous single-page
viewer is still at `/legacy`.

## Development

`make check` runs the linters, type checks and unit tests; `make e2e` runs the Playwright recipes. Both
need the local database (`make db-start`, Docker). CONTRIBUTING.md lists every quality gate, how the git
hooks and CI mirror each other, and the database workflow; CLAUDE.md holds the conventions for working
with Claude Code, including when to write Rust instead of Python.

The web UI is plain ES modules with no build step. Its components (Shoelace) and fonts are vendored, so
the page makes no external requests. Quote verification has an optional Rust build, `./build-rust.sh`;
without it the Python implementation runs.
