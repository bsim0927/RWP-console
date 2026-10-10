#!/usr/bin/env bash
# Migration consistency: replaying supabase/migrations must produce exactly the declared schema in
# supabase/schemas. `supabase db schema declarative sync --no-apply` writes a new migration file for any
# difference between the two (it builds both in a shadow database, so it needs Docker). A new file
# therefore means drift; it is printed, removed, and the check fails.
#
# Fix drift by keeping the generated migration:  npx supabase db schema declarative sync --name <change>
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
shopt -s nullglob
schemas=(supabase/schemas/*.sql)
if [[ ${#schemas[@]} -eq 0 ]]; then
  echo "schema drift: no declared schemas in supabase/schemas yet, skipping"
  exit 0
fi
mkdir -p supabase/migrations
before=$(ls supabase/migrations)
npx --no-install supabase db schema declarative sync --no-apply --name schema_drift_check
added=$(comm -13 <(echo "$before") <(ls supabase/migrations))
if [[ -n $added ]]; then
  echo "::error file=supabase/schemas::migrations do not produce the declared schema"
  echo "Schema drift. Replaying supabase/migrations does not produce supabase/schemas. Missing change:"
  for f in $added; do cat "supabase/migrations/$f"; rm "supabase/migrations/$f"; done
  echo "Generate the migration with: npx supabase db schema declarative sync --name <describe_the_change>"
  exit 1
fi
echo "schema drift: none (${#schemas[@]} schema file(s))"
