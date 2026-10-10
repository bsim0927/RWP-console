#!/usr/bin/env bash
# Migration consistency: the database built by replaying supabase/migrations must match the declared
# schema in supabase/schemas (declarative schemas). `supabase db diff` prints the SQL needed to turn
# the migrated database into the declared one; any output means they have drifted apart.
#
# Fix drift by generating the missing migration:  npx supabase db diff -f <name>
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
shopt -s nullglob
schemas=(supabase/schemas/*.sql)
if [[ ${#schemas[@]} -eq 0 ]]; then
  echo "schema drift: no declared schemas in supabase/schemas yet, skipping"
  exit 0
fi
diff_sql=$(npx --no-install supabase db diff --local 2>/dev/null | grep -vE '^\s*(--.*)?$' || true)
if [[ -n $diff_sql ]]; then
  echo "::error file=supabase/schemas::migrations do not produce the declared schema"
  echo "Schema drift. Replaying supabase/migrations does not produce supabase/schemas. Missing change:"
  echo "$diff_sql"
  echo "Generate the migration with: npx supabase db diff -f <describe_the_change>"
  exit 1
fi
echo "schema drift: none (${#schemas[@]} schema file(s))"
