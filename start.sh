#!/usr/bin/env bash
#
# MC Server Manager — Development Launcher (Unix)
# ===============================================
# Wrapper around launcher.py for convenience.
# Usage: ./start.sh [--stop|--restart|--status|--code|--help]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${SCRIPT_DIR}/launcher.py"
PYTHON=""

# Detect Python
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo ""
    echo "  ✖ Python is not installed."
    echo "  Install Python 3.12+ from https://python.org"
    echo ""
    exit 1
fi

# Detect venv
VENV_PYTHON="${SCRIPT_DIR}/backend/.venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
fi

# Check launcher exists
if [ ! -f "$LAUNCHER" ]; then
    echo ""
    echo "  ✖ launcher.py not found in ${SCRIPT_DIR}"
    echo "  The launcher must be in the same directory as this script."
    echo ""
    exit 1
fi

# Preflight: kill stale/duplicate processes before starting anything
PREFLIGHT="${SCRIPT_DIR}/scripts/preflight.sh"
if [ -x "$PREFLIGHT" ]; then
    if ! "$PREFLIGHT"; then
        echo ""
        echo "  ✖ Preflight check failed. Fix the issues above and try again."
        echo ""
        exit 1
    fi
else
    echo ""
    echo "  ⚠ Preflight script not found at ${PREFLIGHT} — skipping cleanup."
    echo ""
fi

# Forward all arguments
exec "$PYTHON" "$LAUNCHER" "$@"
