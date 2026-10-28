#!/usr/bin/env bash
# Wire this into .git/hooks/pre-push (or call it manually before pushing).

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Stray SQLite DB guard — hard block against unanchored/stray .db files in repo root or backend root
if [ -f "$REPO_ROOT/scripts/check-stray-db" ]; then
  if ! python3 "$REPO_ROOT/scripts/check-stray-db"; then
    echo "❌ Pre-push check failed: stray SQLite files found in repo or backend root."
    echo "   Remove stray DB files or configure scripts to use tmp_path before pushing."
    exit 1
  fi
fi

exit 0
