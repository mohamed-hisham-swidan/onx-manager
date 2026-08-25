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

# 1. Detect existing backend venv
VENV_PYTHON="${SCRIPT_DIR}/backend/.venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    if "$VENV_PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
        PYTHON="$VENV_PYTHON"
    fi
fi

# 2. If no valid venv, detect system Python 3.12+
if [ -z "$PYTHON" ]; then
    for cmd in python3.13 python3.12 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
                PYTHON="$(command -v "$cmd")"
                break
            fi
        fi
    done
fi

# 3. If Python 3.12+ is still not found, attempt automatic installation
if [ -z "$PYTHON" ]; then
    echo ""
    echo "  ⚠ Python 3.12+ not found. Attempting automatic installation..."

    # Try uv if available
    if command -v uv &>/dev/null; then
        echo "  ▸ Installing Python 3.12 via uv..."
        uv python install 3.12 && PYTHON="$(uv python find 3.12 2>/dev/null || true)"
    fi

    # Try apt (Debian / Ubuntu)
    if [ -z "$PYTHON" ] && command -v apt-get &>/dev/null; then
        echo "  ▸ Installing Python via apt..."
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip || true
        PYTHON="$(command -v python3 || true)"
    fi

    # Try dnf (Fedora / RHEL)
    if [ -z "$PYTHON" ] && command -v dnf &>/dev/null; then
        echo "  ▸ Installing Python via dnf..."
        sudo dnf install -y python3 python3-pip || true
        PYTHON="$(command -v python3 || true)"
    fi

    # Try pacman (Arch Linux)
    if [ -z "$PYTHON" ] && command -v pacman &>/dev/null; then
        echo "  ▸ Installing Python via pacman..."
        sudo pacman -S --noconfirm python python-pip || true
        PYTHON="$(command -v python3 || true)"
    fi

    # Try brew (macOS / Linuxbrew)
    if [ -z "$PYTHON" ] && command -v brew &>/dev/null; then
        echo "  ▸ Installing Python via Homebrew..."
        brew install python@3.12 || true
        PYTHON="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
    fi
fi

if [ -z "$PYTHON" ] || ! "$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
    echo ""
    echo "  ✖ Python 3.12+ is not installed or could not be detected."
    echo "  Please install Python 3.12+ from https://python.org or via your package manager."
    echo ""
    exit 1
fi

# 4. Check launcher exists
if [ ! -f "$LAUNCHER" ]; then
    echo ""
    echo "  ✖ launcher.py not found in ${SCRIPT_DIR}"
    echo "  The launcher must be in the same directory as this script."
    echo ""
    exit 1
fi

# 5. Preflight: kill stale/duplicate processes before starting anything
PREFLIGHT="${SCRIPT_DIR}/scripts/preflight.sh"
if [ -x "$PREFLIGHT" ]; then
    if ! "$PREFLIGHT" "$@"; then
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

# 6. Forward all arguments
exec "$PYTHON" "$LAUNCHER" "$@"
