#!/usr/bin/env bash
# Playwright's webServer: build the fixture (data rooms + the rwp_e2e database), then serve the repo's
# app against it. Never touches .env's DATABASE_URL or the real data root.
set -euo pipefail
cd "$(dirname "$0")/../.."
ws="${E2E_WORKSPACE:-e2e/.workspace}"
out="$(uv run --frozen python e2e/fixtures/build.py "$ws")"
data_root="$(sed -n '1p' <<<"$out")"
DATABASE_URL="$(sed -n '2p' <<<"$out")"
export DATABASE_URL
exec uv run --frozen python server.py "$data_root"
