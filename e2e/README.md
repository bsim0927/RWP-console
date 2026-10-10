# Playwright recipes

Browser tests that catch frontend bugs, run against a synthetic, deterministic workspace.

    make e2e                        # all recipes, desktop + mobile
    npx playwright test --ui        # interactive, with time travel
    npx playwright test fund        # one file
    npx playwright show-report e2e/.report

## How it works

`e2e/fixtures/serve.sh` (Playwright's `webServer`) builds `e2e/.workspace/`: a copy of the app plus
three invented data rooms (`fixtures/build.py`). It runs the real catalog and screening pipeline over
them with scripted extractor and judge stubs, so every view shows genuine run output, with no API keys,
no network, and none of RWP's real documents. The fixture covers Pass, Fail, Route with disclosure,
Incomplete, Not yet run, analyst review, a rejected (fabricated) quote, and an unscreened fund.
Tests may change gates freely; the repo's own `gates/`, `runs/` and `catalog/` are never touched.

## The harness

Import `test` from `recipes/fixtures.js`, not from `@playwright/test`. It fails the test on:

- an uncaught exception
- `console.error`
- a request that fails outright
- any `/api/` response with status 400 or above

A recipe that expects one of these declares it: `allow.api(/\/api\/raw/)`, `allow.console(/.../)`.

## Recipes

| File | Catches |
|---|---|
| `smoke.spec.js` | a view that throws or fails to render (`@smoke`, also run on Vercel previews) |
| `navigation.spec.js` | broken routing, active-state, history and deep links |
| `screening.spec.js` | queue, filter counts and badges disagreeing with the runs on disk |
| `fund.spec.js` | gate cards, gate drawer, citations opening the right PDF page, tabs |
| `search.spec.js` | document search, the omni box and `/` shortcut, XSS in search terms |
| `api.spec.js` | API contract changes and path traversal on `/api/raw` and static files |
| `a11y.spec.js` | critical axe violations (serious ones are attached to the report) |
| `responsive.spec.js` | horizontal page overflow, at desktop and phone width (`@responsive`) |

## Writing a recipe for a bug

1. Reproduce it in the fixture. If the bug needs data the fixture lacks, add it to `fixtures/build.py`
   (invented names only).
2. Write the failing test in the closest recipe file, named for the behaviour the user expects.
3. Fix the bug; the test goes green and stays as a regression guard.
4. For intermittent bugs, prove the fix: `npx playwright test <file> --repeat-each=20`.

Prefer locators the user would recognise (`getByRole`, visible text) and the app's stable ids; never
`waitForTimeout`. Traces, screenshots and video are kept for failures (`e2e/.results/`).
