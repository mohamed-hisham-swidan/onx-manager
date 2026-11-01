#!/usr/bin/env bash
#
# onx-manager — Development Launcher (Unix)
# =========================================
# Wrapper around launcher.py for convenience.
# Usage: ./start.sh [--stop|--restart|--status|--code|--help]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${SCRIPT_DIR}/launcher.py"
PYTHON=""
PINNED_PYTHON="3.12"
# Exact probe helper string (matches SPEC-2026-10-29 §4.3: sys.version_info[:2] == (3,12))
PYTHON_EXACT_PROBE='import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
PYTHON_EXEC_PROBE='import sys; print(sys.executable)'

is_python_312() {
    local cmd="${1:-}"
    [ -n "$cmd" ] || return 1
    if command -v timeout &>/dev/null; then
        timeout 10 "$cmd" -c "$PYTHON_EXACT_PROBE" &>/dev/null
    else
        "$cmd" -c "$PYTHON_EXACT_PROBE" &>/dev/null
    fi
}

# 1. Detect existing backend venv
VENV_PYTHON="${SCRIPT_DIR}/backend/.venv/bin/python"
if [ -x "$VENV_PYTHON" ] && is_python_312 "$VENV_PYTHON"; then
    PYTHON="$VENV_PYTHON"
fi

# 2. If no valid venv, detect system Python 3.12
if [ -z "$PYTHON" ]; then
    for cmd in python3.12 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            cand="$(command -v "$cmd")"
            if is_python_312 "$cand"; then
                PYTHON="$cand"
                break
            fi
        fi
    done
fi

# 3. If Python 3.12 is still not found, attempt automatic installation
if [ -z "$PYTHON" ]; then
    echo ""
    echo "  ⚠ Python 3.12 not found. Attempting automatic installation..."

    # Try uv if available
    if command -v uv &>/dev/null; then
        echo "  ▸ Installing Python 3.12 via uv..."
        uv python install 3.12 || true
        cand="$(uv python find 3.12 2>/dev/null || true)"
        if is_python_312 "$cand"; then
            PYTHON="$cand"
        fi
    fi

    # Try apt (Debian / Ubuntu)
    if [ -z "$PYTHON" ] && command -v apt-get &>/dev/null; then
        echo "  ▸ Installing Python via apt..."
        sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv || true
        cand="$(command -v python3.12 || true)"
        if is_python_312 "$cand"; then
            PYTHON="$cand"
        fi
    fi

    # Try dnf (Fedora / RHEL)
    if [ -z "$PYTHON" ] && command -v dnf &>/dev/null; then
        echo "  ▸ Installing Python via dnf..."
        sudo dnf install -y python3.12 || true
        cand="$(command -v python3.12 || true)"
        if is_python_312 "$cand"; then
            PYTHON="$cand"
        fi
    fi

    # Try brew (macOS / Linuxbrew)
    if [ -z "$PYTHON" ] && command -v brew &>/dev/null; then
        echo "  ▸ Installing Python via Homebrew..."
        brew install python@3.12 || true
        cand="$(brew --prefix python@3.12 2>/dev/null || true)/bin/python3.12"
        if is_python_312 "$cand"; then
            PYTHON="$cand"
        fi
    fi
fi

if [ -z "$PYTHON" ] || ! is_python_312 "$PYTHON"; then
    echo ""
    echo "  ✖ Python 3.12.x is required. onx-manager does not support Python 3.13/3.14."
    echo "  Install Python 3.12 with one of: 'uv python install 3.12' (recommended),"
    echo "  'brew install python@3.12' (macOS), or your distro's python3.12 package,"
    echo "  then re-run ./start.sh."
    echo ""
    exit 1
fi

# 3b. Detect or auto-install Node.js 18+ and npm
NODE_OK=0
if command -v node &>/dev/null; then
    NODE_VER="$(node -v 2>/dev/null || echo "")"
    NODE_MAJOR="$(echo "$NODE_VER" | sed -E 's/^v([0-9]+).*/\1/')"
    if [ -n "$NODE_MAJOR" ] && [ "$NODE_MAJOR" -ge 18 ]; then
        NODE_OK=1
    fi
fi

if [ "$NODE_OK" -eq 0 ]; then
    echo ""
    echo "  ⚠ Node.js 18+ not found on PATH. Attempting automatic installation..."

    if command -v brew &>/dev/null; then
        echo "  ▸ Installing Node.js via Homebrew..."
        brew install node@22 || true
    elif command -v apt-get &>/dev/null; then
        echo "  ▸ Installing Node.js via NodeSource / apt..."
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs || true
    elif command -v dnf &>/dev/null; then
        echo "  ▸ Installing Node.js via dnf..."
        sudo dnf install -y nodejs || true
    elif command -v pacman &>/dev/null; then
        echo "  ▸ Installing Node.js via pacman..."
        sudo pacman -S --noconfirm nodejs npm || true
    fi
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
