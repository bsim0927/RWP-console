#!/usr/bin/env bash
# Playwright's webServer: build a fresh fixture workspace, then serve it. Never touches the repo's
# gates/, runs/ or catalog/.
set -euo pipefail
cd "$(dirname "$0")/../.."
ws="${E2E_WORKSPACE:-e2e/.workspace}"
data_root="$(uv run --frozen python e2e/fixtures/build.py "$ws" | tail -1)"
cd "$ws"
exec uv run --frozen --project "$OLDPWD" python server.py "$data_root"
