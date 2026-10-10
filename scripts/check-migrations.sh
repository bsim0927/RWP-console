#!/usr/bin/env bash
# Static migration hygiene. No database needed, so it runs in pre-commit as well as CI.
#
#   scripts/check-migrations.sh [base-ref]
#
# Always:
#   - names are <14-digit UTC timestamp>_<snake_case>.sql, the format `supabase migration new` writes
#   - timestamps are unique (two branches that each add a migration in the same second collide)
#   - no migration is empty
# With a base ref (CI passes the PR base, e.g. origin/main):
#   - migrations already on the base are append-only: never edited, renamed or deleted, because
#     environments that already applied them will not re-run them
#   - new migrations sort after the newest one on the base, or they would apply out of order
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
dir=supabase/migrations
base="${1:-}"
fail=0
err() { echo "::error file=$1::$2" >&2; echo "migrations: $1: $2" >&2; fail=1; }

shopt -s nullglob
files=("$dir"/*.sql)
for f in "${files[@]}"; do
  name=$(basename "$f")
  [[ $name =~ ^[0-9]{14}_[a-z0-9_]+\.sql$ ]] || err "$f" "name must be <YYYYMMDDHHMMSS>_<snake_case>.sql (use: npx supabase migration new <name>)"
  grep -qvE '^\s*(--.*)?$' "$f" || err "$f" "migration has no SQL"
done
dupes=$(printf '%s\n' "${files[@]##*/}" | cut -c1-14 | sort | uniq -d)
[[ -z $dupes ]] || err "$dir" "duplicate migration timestamps: $dupes"

if [[ -n $base ]]; then
  changed=$(git diff --name-status --diff-filter=MDR "$base"...HEAD -- "$dir" | grep '\.sql' || true)
  [[ -z $changed ]] || err "$dir" "migrations on $base are append-only; add a new migration instead of changing:"$'\n'"$changed"
  newest_base=$(git ls-tree --name-only "$base" "$dir/" 2>/dev/null | grep -E '/[0-9]{14}_.*\.sql$' | xargs -rn1 basename | sort | tail -1 || true)
  if [[ -n $newest_base ]]; then
    for f in $(git diff --name-only --diff-filter=A "$base"...HEAD -- "$dir" | grep '\.sql$' || true); do
      [[ $(basename "$f") > $newest_base ]] || err "$f" "sorts before $newest_base, already on $base; regenerate it with a newer timestamp"
    done
  fi
fi

[[ $fail -eq 0 ]] && echo "migrations: ${#files[@]} file(s) OK${base:+ against $base}"
exit $fail
