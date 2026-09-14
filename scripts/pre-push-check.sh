#!/usr/bin/env bash
# .ai/STATE.json freshness check — reminder, not a hard gate.
# Wire this into .git/hooks/pre-push (or call it manually before pushing) to
# catch the "code changed, docs/state didn't" pattern that produced the
# conflicting state files this project used to have.

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
STATE_FILE="$REPO_ROOT/.ai/STATE.json"

if [ ! -f "$STATE_FILE" ]; then
  echo "⚠️  .ai/STATE.json not found — skipping freshness check."
  exit 0
fi

LAST_UPDATED=$(grep -o '"last_updated"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATE_FILE" | sed -E 's/.*"([0-9-]+)"$/\1/')
TODAY=$(date +%Y-%m-%d)

# Has anything outside .ai/ or docs/ changed in the commits about to be pushed?
CHANGED_FILES=$(git diff --name-only @{u}.. 2>/dev/null || git diff --name-only HEAD~5..HEAD 2>/dev/null || echo "")
SUBSTANTIVE_CHANGE=$(echo "$CHANGED_FILES" | grep -vE '^(\.ai/|docs/)' | head -1)

if [ -n "$SUBSTANTIVE_CHANGE" ] && [ "$LAST_UPDATED" != "$TODAY" ]; then
  echo "⚠️  Code changed but .ai/STATE.json's last_updated is '$LAST_UPDATED', not today ($TODAY)."
  echo "    If this push includes a real state change (tests, migrations, phase status),"
  echo "    update .ai/STATE.json before pushing. This is a reminder, not a block —"
  echo "    press Ctrl+C to stop and fix, or press Enter to push anyway."
  read -r _
fi

# Stray SQLite DB guard — hard block against unanchored/stray .db files in repo root or backend root
if [ -f "$REPO_ROOT/scripts/check-stray-db" ]; then
  if ! python3 "$REPO_ROOT/scripts/check-stray-db"; then
    echo "❌ Pre-push check failed: stray SQLite files found in repo or backend root."
    echo "   Remove stray DB files or configure scripts to use tmp_path before pushing."
    exit 1
  fi
fi

exit 0
