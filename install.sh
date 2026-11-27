#!/usr/bin/env bash
# ==============================================================================
# ONX Manager — Standard Installer (Linux / macOS)
# ==============================================================================
# Usage (local checkout):
#   ./install.sh [options]
#
# Usage (one-line curl-pipe):
#   curl -fsSL https://raw.githubusercontent.com/mohamed-hisham-swidan/onx-manager/master/install.sh | bash
#
# Options:
#   --mode=vps|local     Deployment profile (vps = full server panel + systemd;
#                        local = streamlined personal desktop + app launcher)
#   --dir=<path>         Installation directory
#   --port=<port>        Backend HTTP port (1024..65535, default: 8000)
#   --host=<bind_host>   Bind address (default: 0.0.0.0 for vps, 127.0.0.1 for local)
#   --yes, -y            Accept defaults without interactive prompts
#   --verbose            Show full installer command output
#   --dry-run            Validate arguments and print planned actions without modifying system
#   --uninstall          Remove ONX Manager service, CLI wrapper, and desktop launcher
#   --help, -h           Show this help message
# ==============================================================================

set -euo pipefail

ONX_REPO_URL="${ONX_REPO_URL:-https://github.com/mohamed-hisham-swidan/onx-manager.git}"
ONX_REPO_BRANCH="${ONX_REPO_BRANCH:-master}"
PYTHON_EXACT_PROBE='import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'

MODE=""
INSTALL_DIR=""
PORT="8000"
BIND_HOST=""
AUTO_YES=0
VERBOSE=0
DRY_RUN=0
UNINSTALL=0

BOLD=""
DIM=""
GREEN=""
YELLOW=""
RED=""
CYAN=""
RESET=""
if [ -t 1 ]; then
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    RED=$'\033[31m'
    CYAN=$'\033[36m'
    RESET=$'\033[0m'
fi

log_info()  { printf "  %s▸%s %s\n" "${CYAN}" "${RESET}" "$1"; }
log_ok()    { printf "  %s✓%s %s\n" "${GREEN}" "${RESET}" "$1"; }
log_warn()  { printf "  %s⚠%s %s\n" "${YELLOW}" "${RESET}" "$1" >&2; }
log_err()   { printf "  %s✖%s %s\n" "${RED}" "${RESET}" "$1" >&2; }

print_help() {
    cat <<'EOF'
ONX Manager Installer (v0.1.0)

Usage:
  ./install.sh [options]
  curl -fsSL https://raw.githubusercontent.com/mohamed-hisham-swidan/onx-manager/master/install.sh | bash

Options:
  --mode=vps|local     Deployment profile:
                         vps   Full server panel, systemd service, onx CLI
                         local Personal machine panel, ~/.local/bin/onx, desktop icon
  --dir=<path>         Installation directory
  --port=<port>        HTTP port (1024..65535, default: 8000)
  --host=<bind_host>   Bind IP (default: 0.0.0.0 for vps, 127.0.0.1 for local)
  --yes, -y            Non-interactive mode (accept defaults)
  --verbose            Stream full uv/npm/alembic output
  --dry-run            Validate arguments and print planned steps without making changes
  --uninstall          Stop service and remove onx CLI / desktop entry (preserves data)
  --help, -h           Show this help message
EOF
}

parse_port() {
    local val="$1"
    if [[ ! "$val" =~ ^[0-9]+$ ]] || [ "$val" -lt 1024 ] || [ "$val" -gt 65535 ]; then
        log_err "Invalid port '$val' (must be an integer between 1024 and 65535)."
        exit 1
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --mode=*)
            MODE="${1#*=}"
            ;;
        --mode)
            shift
            [ $# -gt 0 ] || { log_err "--mode requires a value (vps|local)"; exit 1; }
            MODE="$1"
            ;;
        --dir=*)
            INSTALL_DIR="${1#*=}"
            ;;
        --dir)
            shift
            [ $# -gt 0 ] || { log_err "--dir requires a path"; exit 1; }
            INSTALL_DIR="$1"
            ;;
        --port=*)
            PORT="${1#*=}"
            ;;
        --port)
            shift
            [ $# -gt 0 ] || { log_err "--port requires a port number"; exit 1; }
            PORT="$1"
            ;;
        --host=*)
            BIND_HOST="${1#*=}"
            ;;
        --host)
            shift
            [ $# -gt 0 ] || { log_err "--host requires a bind address"; exit 1; }
            BIND_HOST="$1"
            ;;
        --yes|-y)
            AUTO_YES=1
            ;;
        --verbose)
            VERBOSE=1
            ;;
        --dry-run)
            DRY_RUN=1
            ;;
        --uninstall)
            UNINSTALL=1
            ;;
        --help|-h)
            print_help
            exit 0
            ;;
        *)
            log_err "Unknown option: $1 (use --help for usage)"
            exit 1
            ;;
    esac
    shift
done

parse_port "$PORT"

if [ -n "$MODE" ] && [ "$MODE" != "vps" ] && [ "$MODE" != "local" ]; then
    log_err "Invalid mode '$MODE'. Choose 'vps' or 'local'."
    exit 1
fi

prompt_read() {
    local prompt_text="$1"
    local default_val="$2"
    local reply=""
    if [ "$AUTO_YES" -eq 1 ]; then
        printf "%s" "$default_val"
        return 0
    fi
    if [ -t 0 ]; then
        read -r -p "$prompt_text" reply || true
    elif [ -r /dev/tty ]; then
        read -r -p "$prompt_text" reply </dev/tty || true
    else
        printf "%s" "$default_val"
        return 0
    fi
    printf "%s" "${reply:-$default_val}"
}

detect_local_repo_root() {
    local src="${BASH_SOURCE[0]:-}"
    if [ -n "$src" ] && [ "$src" != "bash" ] && [ "$src" != "-" ] && [ -f "$src" ]; then
        local dir
        dir="$(cd "$(dirname "$src")" && pwd)"
        if [ -f "${dir}/backend/pyproject.toml" ] && [ -f "${dir}/frontend/package.json" ]; then
            printf "%s" "$dir"
            return 0
        fi
    fi
    local cwd
    cwd="$(pwd)"
    if [ -f "${cwd}/backend/pyproject.toml" ] && [ -f "${cwd}/frontend/package.json" ]; then
        printf "%s" "$cwd"
        return 0
    fi
    return 1
}

run_step() {
    local label="$1"
    shift
    if [ "$VERBOSE" -eq 1 ]; then
        log_info "$label..."
        "$@"
        log_ok "$label"
        return 0
    fi
    local tmp_log
    tmp_log="$(mktemp)"
    printf "  %s▸%s %s..." "${CYAN}" "${RESET}" "$label"
    if "$@" >"$tmp_log" 2>&1; then
        printf "\r  %s✓%s %s   \n" "${GREEN}" "${RESET}" "$label"
        rm -f "$tmp_log"
        return 0
    else
        local rc=$?
        printf "\r  %s✖%s %s   \n" "${RED}" "${RESET}" "$label" >&2
        tail -n 40 "$tmp_log" >&2 || true
        rm -f "$tmp_log"
        return "$rc"
    fi
}

run_as_root_cmd() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        return 1
    fi
}

if [ "$UNINSTALL" -eq 1 ]; then
    echo ""
    printf "  %sONX Manager — Uninstaller%s\n" "${BOLD}" "${RESET}"
    echo ""
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [DRY RUN] Would stop/disable onx-manager.service (system or user) if present"
        echo "  [DRY RUN] Would remove /usr/local/bin/onx and ~/.local/bin/onx"
        echo "  [DRY RUN] Would remove ~/.local/share/applications/onx-manager.desktop and icon"
        echo "  [DRY RUN] Would preserve data/servers/config directories"
        exit 0
    fi

    if command -v systemctl >/dev/null 2>&1; then
        if [ -f /etc/systemd/system/onx-manager.service ]; then
            run_as_root_cmd systemctl disable --now onx-manager.service >/dev/null 2>&1 || true
            run_as_root_cmd rm -f /etc/systemd/system/onx-manager.service || true
            run_as_root_cmd systemctl daemon-reload >/dev/null 2>&1 || true
            log_ok "Removed system systemd service onx-manager.service"
        fi
        if [ -f "${HOME}/.config/systemd/user/onx-manager.service" ]; then
            systemctl --user disable --now onx-manager.service >/dev/null 2>&1 || true
            rm -f "${HOME}/.config/systemd/user/onx-manager.service"
            systemctl --user daemon-reload >/dev/null 2>&1 || true
            log_ok "Removed user systemd service onx-manager.service"
        fi
    fi

    for bin_path in "/usr/local/bin/onx" "${HOME}/.local/bin/onx"; do
        if [ -f "$bin_path" ] || [ -L "$bin_path" ]; then
            if [ -w "$(dirname "$bin_path")" ]; then
                rm -f "$bin_path"
            else
                run_as_root_cmd rm -f "$bin_path" || true
            fi
            log_ok "Removed CLI wrapper: $bin_path"
        fi
    done

    rm -f "${HOME}/.local/share/applications/onx-manager.desktop"
    rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/onx-manager.svg"
    log_ok "Removed desktop launcher entry (if present)"
    log_info "User data, worlds, backups, and config keys were preserved."
    exit 0
fi

echo ""
printf "  %sONX Manager Installer (v0.1.0)%s\n" "${BOLD}" "${RESET}"
printf "  %sSelf-hosted Minecraft Server Panel & GitOps Engine%s\n" "${DIM}" "${RESET}"
echo ""

if [ -z "$MODE" ]; then
    if [ "$AUTO_YES" -eq 1 ] || { [ ! -t 0 ] && [ ! -r /dev/tty ]; }; then
        MODE="vps"
    else
        echo "  Choose deployment profile:"
        echo "    1) VPS / Server Mode  — Full panel, systemd service, onx CLI"
        echo "    2) Local / Desktop    — Streamlined personal UI, ~/.local/bin/onx, app icon"
        echo ""
        choice="$(prompt_read "  Select [1/2] (default: 1): " "1")"
        case "$choice" in
            2|local|LOCAL) MODE="local" ;;
            *) MODE="vps" ;;
        esac
    fi
fi

LOCAL_REPO=""
if LOCAL_REPO="$(detect_local_repo_root 2>/dev/null || true)" && [ -n "$LOCAL_REPO" ]; then
    :
else
    LOCAL_REPO=""
fi

if [ -z "$INSTALL_DIR" ]; then
    if [ "$MODE" = "local" ]; then
        if [ -n "$LOCAL_REPO" ]; then
            INSTALL_DIR="$LOCAL_REPO"
        else
            INSTALL_DIR="${HOME}/.local/share/onx-manager"
        fi
    else
        if [ -n "$LOCAL_REPO" ]; then
            INSTALL_DIR="$LOCAL_REPO"
        elif [ "$(id -u)" -eq 0 ] || command -v sudo >/dev/null 2>&1; then
            INSTALL_DIR="/opt/onx-manager"
        else
            INSTALL_DIR="${HOME}/.local/share/onx-manager"
        fi
    fi
fi

if [ -z "$BIND_HOST" ]; then
    if [ "$MODE" = "local" ]; then
        BIND_HOST="127.0.0.1"
    else
        BIND_HOST="0.0.0.0"
    fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [DRY RUN] Installer Plan"
    echo "    ONX_DEPLOYMENT_PROFILE=${MODE}"
    echo "    INSTALL_DIR=${INSTALL_DIR}"
    echo "    ONX_PANEL_BIND_HOST=${BIND_HOST}"
    echo "    ONX_PANEL_BIND_PORT=${PORT}"
    echo "    PYTHON_PIN=3.12 (exact via uv)"
    if [ "$MODE" = "vps" ]; then
        echo "    SERVICE=systemd (onx-manager.service)"
        echo "    CLI=onx (start|stop|restart|status|logs|update|open)"
    else
        echo "    DESKTOP_ENTRY=~/.local/share/applications/onx-manager.desktop"
        echo "    CLI=~/.local/bin/onx (start|stop|restart|status|logs|open|update)"
    fi
    exit 0
fi

# 1. Preflight Docker availability & daemon permissions (honest warning)
check_docker_preflight() {
    if ! command -v docker >/dev/null 2>&1; then
        log_warn "Docker CLI not found in PATH."
        log_warn "Minecraft servers run inside Docker containers; panel startup will succeed,"
        log_warn "but creating/starting servers requires Docker Engine (https://docs.docker.com/engine/install/)."
        return 0
    fi
    if docker info >/dev/null 2>&1; then
        log_ok "Docker daemon reachable"
    else
        log_warn "Docker is installed, but the current user ($(id -un)) cannot access the Docker daemon."
        log_warn "Ensure Docker is running and grant socket permissions before creating servers:"
        log_warn "  sudo systemctl enable --now docker"
        log_warn "  sudo usermod -aG docker \$USER && newgrp docker"
    fi
}

check_docker_preflight

# 2. Ensure repository files exist in INSTALL_DIR
if [ ! -f "${INSTALL_DIR}/backend/pyproject.toml" ]; then
    if ! command -v git >/dev/null 2>&1; then
        log_err "git is required to clone ONX Manager into ${INSTALL_DIR}."
        exit 1
    fi
    if [ ! -w "$(dirname "$INSTALL_DIR")" ] && [ "$(id -u)" -ne 0 ]; then
        run_as_root_cmd mkdir -p "$INSTALL_DIR"
        run_as_root_cmd chown "$(id -u):$(id -g)" "$INSTALL_DIR"
    else
        mkdir -p "$INSTALL_DIR"
    fi
    run_step "Cloning ONX Manager (${ONX_REPO_BRANCH}) into ${INSTALL_DIR}" \
        git clone --depth 1 --branch "$ONX_REPO_BRANCH" "$ONX_REPO_URL" "$INSTALL_DIR"
else
    log_ok "Using existing workspace at ${INSTALL_DIR}"
fi

INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
BACKEND_DIR="${INSTALL_DIR}/backend"
FRONTEND_DIR="${INSTALL_DIR}/frontend"
VENV_DIR="${BACKEND_DIR}/.venv"
VENV_PY="${VENV_DIR}/bin/python"

# 2. Ensure uv is installed and provision isolated Python 3.12
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
if ! command -v uv >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1; then
        run_step "Installing uv package manager" bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
        export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
    fi
fi

if command -v uv >/dev/null 2>&1; then
    run_step "Provisioning isolated Python 3.12 via uv" uv python install 3.12
    if [ ! -x "$VENV_PY" ] || ! "$VENV_PY" -c "$PYTHON_EXACT_PROBE" >/dev/null 2>&1; then
        if [ -e "$VENV_DIR" ] && [ ! -L "$VENV_DIR" ]; then
            log_warn "Recreating stale virtualenv at ${VENV_DIR} with Python 3.12"
            uv venv --clear --python 3.12 "$VENV_DIR"
        else
            run_step "Creating Python 3.12 virtualenv" uv venv --python 3.12 "$VENV_DIR"
        fi
    fi
    run_step "Installing backend Python 3.12 dependencies" \
        uv pip install --python "$VENV_PY" -r "${BACKEND_DIR}/requirements.txt"
    run_step "Installing ONX Manager backend package" \
        uv pip install --python "$VENV_PY" --no-deps -e "$BACKEND_DIR"
else
    # Fallback when uv cannot be installed (exact Python 3.12 required, no 3.13/3.14 fallback)
    PY312=""
    for cmd in python3.12 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            cand="$(command -v "$cmd")"
            if "$cand" -c "$PYTHON_EXACT_PROBE" >/dev/null 2>&1; then
                PY312="$cand"
                break
            fi
        fi
    done
    if [ -z "$PY312" ]; then
        echo "" >&2
        echo "  ✖ Python 3.12.x is required. onx-manager does not support Python 3.13/3.14." >&2
        echo "  Install Python 3.12 with one of: 'uv python install 3.12' (recommended)," >&2
        echo "  'brew install python@3.12' (macOS), or your distro's python3.12 package," >&2
        echo "  then re-run ./install.sh." >&2
        echo "" >&2
        exit 1
    fi
    if [ ! -x "$VENV_PY" ] || ! "$VENV_PY" -c "$PYTHON_EXACT_PROBE" >/dev/null 2>&1; then
        run_step "Creating Python 3.12 virtualenv" "$PY312" -m venv "$VENV_DIR"
    fi
    run_step "Installing backend Python 3.12 dependencies" \
        "$VENV_PY" -m pip install -r "${BACKEND_DIR}/requirements.txt"
    run_step "Installing ONX Manager backend package" \
        "$VENV_PY" -m pip install --no-deps -e "$BACKEND_DIR"
fi

# 3. Build static frontend SPA bundle if missing (zero Node.js runtime dependency afterward)
if [ ! -f "${FRONTEND_DIR}/dist/index.html" ]; then
    if command -v npm >/dev/null 2>&1; then
        run_step "Installing frontend build dependencies" npm --prefix "$FRONTEND_DIR" ci
        run_step "Building production frontend SPA bundle" npm --prefix "$FRONTEND_DIR" run build
    else
        log_warn "npm not found and frontend/dist/index.html is missing — backend will start API-only until frontend/dist is built."
    fi
else
    log_ok "Static frontend bundle present (${FRONTEND_DIR}/dist)"
fi

# 4. Generate missing 0600 secrets (never overwrite existing keys) & write .env
CONFIG_DIR="${BACKEND_DIR}/config"
mkdir -p "$CONFIG_DIR" "${BACKEND_DIR}/data/servers" "${BACKEND_DIR}/data/backups"
chmod 700 "$CONFIG_DIR"

"$VENV_PY" - "$CONFIG_DIR" <<'PYEOF'
import os
import secrets
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

cfg = Path(sys.argv[1])
jwt_path = cfg / "jwt_private_key.pem"
if not jwt_path.exists():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    jwt_path.write_bytes(pem)
    os.chmod(jwt_path, 0o600)

backup_path = cfg / "backup_encryption_key.bin"
if not backup_path.exists():
    backup_path.write_bytes(os.urandom(32))
    os.chmod(backup_path, 0o600)

kek_path = cfg / "master_kek.key"
if not kek_path.exists():
    kek_path.write_text(secrets.token_hex(32) + "\n", encoding="ascii")
    os.chmod(kek_path, 0o600)
PYEOF
log_ok "Verified 0600 cryptographic keys in ${CONFIG_DIR}"

ENV_FILE="${INSTALL_DIR}/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<EOF
# Generated by ONX Manager installer
ONX_DEPLOYMENT_PROFILE=${MODE}
ONX_PANEL_BIND_HOST=${BIND_HOST}
ONX_PANEL_BIND_PORT=${PORT}
ONX_STATIC_DIR=${FRONTEND_DIR}/dist
ONX_DATABASE_URL=sqlite+aiosqlite:///${BACKEND_DIR}/data/onx.db
ONX_JWT_PRIVATE_KEY_PATH=${CONFIG_DIR}/jwt_private_key.pem
ONX_BACKUP_ENCRYPTION_KEY_PATH=${CONFIG_DIR}/backup_encryption_key.bin
ONX_MASTER_KEK_FILE=${CONFIG_DIR}/master_kek.key
EOF
    chmod 600 "$ENV_FILE"
    log_ok "Created environment configuration at ${ENV_FILE}"
else
    # Append deployment profile / static dir if not already configured
    grep -q '^ONX_DEPLOYMENT_PROFILE=' "$ENV_FILE" || echo "ONX_DEPLOYMENT_PROFILE=${MODE}" >> "$ENV_FILE"
    grep -q '^ONX_STATIC_DIR=' "$ENV_FILE" || echo "ONX_STATIC_DIR=${FRONTEND_DIR}/dist" >> "$ENV_FILE"
    grep -q '^ONX_MASTER_KEK' "$ENV_FILE" || echo "ONX_MASTER_KEK_FILE=${CONFIG_DIR}/master_kek.key" >> "$ENV_FILE"
    log_ok "Preserved existing ${ENV_FILE} (ensured profile & static config)"
fi

# 5. Run database migrations
run_step "Running Alembic database migrations" bash -c "
    set -a
    [ -f '${ENV_FILE}' ] && . '${ENV_FILE}'
    set +a
    cd '${BACKEND_DIR}' && '${VENV_DIR}/bin/alembic' upgrade head
"

# 6. Install 'onx' CLI wrapper
write_onx_cli() {
    local target="$1"
    cat > "$target" <<EOF
#!/usr/bin/env bash
set -euo pipefail
ONX_HOME="${INSTALL_DIR}"
VENV_PY="\${ONX_HOME}/backend/.venv/bin/python"
ENV_FILE="\${ONX_HOME}/.env"
MODE="${MODE}"
PORT="${PORT}"

if [ -f "\$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "\$ENV_FILE"
    set +a
fi

cmd="\${1:-start}"
[ \$# -gt 0 ] && shift || true

use_systemd() {
    command -v systemctl >/dev/null 2>&1 || return 1
    if [ -f /etc/systemd/system/onx-manager.service ]; then
        echo "system"
        return 0
    elif [ -f "\${HOME}/.config/systemd/user/onx-manager.service" ]; then
        echo "user"
        return 0
    fi
    return 1
}

svc_ctl() {
    local scope="\$(use_systemd || true)"
    if [ "\$scope" = "system" ]; then
        if [ "\$(id -u)" -eq 0 ]; then
            systemctl "\$@" onx-manager.service
        else
            sudo systemctl "\$@" onx-manager.service
        fi
    elif [ "\$scope" = "user" ]; then
        systemctl --user "\$@" onx-manager.service
    else
        return 1
    fi
}

case "\$cmd" in
    start)
        if svc_ctl start 2>/dev/null; then
            echo "ONX Manager started via systemd."
        else
            exec "\$VENV_PY" "\${ONX_HOME}/launcher.py" --backend-only --headless --profile "\${ONX_DEPLOYMENT_PROFILE:-\$MODE}" --port "\${ONX_PANEL_BIND_PORT:-\$PORT}" "\$@"
        fi
        ;;
    stop)
        if svc_ctl stop 2>/dev/null; then
            echo "ONX Manager stopped."
        else
            exec "\$VENV_PY" "\${ONX_HOME}/launcher.py" --stop "\$@"
        fi
        ;;
    restart)
        if svc_ctl restart 2>/dev/null; then
            echo "ONX Manager restarted."
        else
            exec "\$VENV_PY" "\${ONX_HOME}/launcher.py" --restart --backend-only --headless --profile "\${ONX_DEPLOYMENT_PROFILE:-\$MODE}" --port "\${ONX_PANEL_BIND_PORT:-\$PORT}" "\$@"
        fi
        ;;
    status)
        if svc_ctl status --no-pager 2>/dev/null; then
            true
        else
            exec "\$VENV_PY" "\${ONX_HOME}/launcher.py" --status "\$@"
        fi
        ;;
    logs)
        scope="\$(use_systemd || true)"
        if [ "\$scope" = "system" ]; then
            exec journalctl -u onx-manager.service -n 100 -f
        elif [ "\$scope" = "user" ]; then
            exec journalctl --user -u onx-manager.service -n 100 -f
        else
            exec "\$VENV_PY" "\${ONX_HOME}/launcher.py" --logs "\$@"
        fi
        ;;
    open)
        if ! curl -fsS "http://127.0.0.1:\${ONX_PANEL_BIND_PORT:-\$PORT}/health" >/dev/null 2>&1; then
            "\$VENV_PY" "\${ONX_HOME}/launcher.py" --backend-only --headless --profile "\${ONX_DEPLOYMENT_PROFILE:-\$MODE}" --port "\${ONX_PANEL_BIND_PORT:-\$PORT}" || true
        fi
        url="http://127.0.0.1:\${ONX_PANEL_BIND_PORT:-\$PORT}/"
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "\$url" >/dev/null 2>&1 &
        elif command -v open >/dev/null 2>&1; then
            open "\$url" >/dev/null 2>&1 &
        else
            echo "Open ONX Manager in your browser: \$url"
        fi
        ;;
    update)
        cd "\$ONX_HOME"
        git pull --ff-only
        exec "\${ONX_HOME}/install.sh" --mode="\${ONX_DEPLOYMENT_PROFILE:-\$MODE}" --dir="\$ONX_HOME" --port="\${ONX_PANEL_BIND_PORT:-\$PORT}" --yes
        ;;
    version)
        echo "ONX Manager v0.1.0 (\${ONX_HOME})"
        ;;
    help|--help|-h)
        echo "Usage: onx {start|stop|restart|status|logs|open|update|version}"
        ;;
    *)
        exec "\$VENV_PY" "\${ONX_HOME}/launcher.py" "\$cmd" "\$@"
        ;;
esac
EOF
    chmod 0755 "$target"
}

if [ "$MODE" = "vps" ] && [ -w /usr/local/bin ]; then
    ONX_BIN="/usr/local/bin/onx"
    write_onx_cli "$ONX_BIN"
elif [ "$MODE" = "vps" ] && command -v sudo >/dev/null 2>&1 && [ "$(uname -s)" = "Linux" ]; then
    TMP_CLI="$(mktemp)"
    write_onx_cli "$TMP_CLI"
    if sudo install -m 0755 "$TMP_CLI" /usr/local/bin/onx 2>/dev/null; then
        ONX_BIN="/usr/local/bin/onx"
        rm -f "$TMP_CLI"
    else
        rm -f "$TMP_CLI"
        mkdir -p "${HOME}/.local/bin"
        ONX_BIN="${HOME}/.local/bin/onx"
        write_onx_cli "$ONX_BIN"
    fi
else
    mkdir -p "${HOME}/.local/bin"
    ONX_BIN="${HOME}/.local/bin/onx"
    write_onx_cli "$ONX_BIN"
fi
log_ok "Installed CLI command: ${ONX_BIN}"

# 7. Mode-specific integration (systemd for VPS vs .desktop app icon for Local)
if [ "$MODE" = "vps" ]; then
    if [ "$(uname -s)" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
        ONX_SERVICE_USER="${SUDO_USER:-$(id -un)}"
        UNIT_CONTENT="[Unit]
Description=ONX Manager Server Panel
After=network.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${ONX_SERVICE_USER}
WorkingDirectory=${BACKEND_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host ${BIND_HOST} --port ${PORT} --workers 1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"
        if [ "$(id -u)" -eq 0 ] || command -v sudo >/dev/null 2>&1; then
            TMP_UNIT="$(mktemp)"
            printf "%s" "$UNIT_CONTENT" > "$TMP_UNIT"
            if run_as_root_cmd install -m 0644 "$TMP_UNIT" /etc/systemd/system/onx-manager.service 2>/dev/null; then
                rm -f "$TMP_UNIT"
                run_as_root_cmd systemctl daemon-reload || true
                run_as_root_cmd systemctl enable --now onx-manager.service || true
                log_ok "Installed and enabled systemd service: onx-manager.service"
            else
                rm -f "$TMP_UNIT"
            fi
        else
            mkdir -p "${HOME}/.config/systemd/user"
            USER_UNIT_CONTENT="$(printf "%s" "$UNIT_CONTENT" | sed '/^User=/d; s/^WantedBy=multi-user\.target$/WantedBy=default.target/')"
            printf "%s\n" "$USER_UNIT_CONTENT" > "${HOME}/.config/systemd/user/onx-manager.service"
            systemctl --user daemon-reload >/dev/null 2>&1 || true
            systemctl --user enable --now onx-manager.service >/dev/null 2>&1 || true
            log_ok "Installed user systemd service: ~/.config/systemd/user/onx-manager.service"
        fi
    else
        log_warn "systemd not detected — start manually with: onx start"
    fi
else
    # Local / Desktop mode: install icon + .desktop entry
    ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
    APP_DIR="${HOME}/.local/share/applications"
    mkdir -p "$ICON_DIR" "$APP_DIR"
    if [ -f "${INSTALL_DIR}/docs/assets/logo.svg" ]; then
        cp "${INSTALL_DIR}/docs/assets/logo.svg" "${ICON_DIR}/onx-manager.svg"
    fi
    cat > "${APP_DIR}/onx-manager.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=ONX Manager
Comment=Self-hosted Minecraft Server Panel
Exec=${ONX_BIN} open
Icon=onx-manager
Terminal=false
Categories=Game;Utility;
StartupNotify=true
EOF
    chmod 0644 "${APP_DIR}/onx-manager.desktop"
    log_ok "Installed desktop launcher: ${APP_DIR}/onx-manager.desktop"
fi

echo ""
printf "  %s══════════════════════════════════════════════════════%s\n" "${DIM}" "${RESET}"
printf "  %sONX Manager installed successfully (%s mode)%s\n" "${GREEN}${BOLD}" "$MODE" "${RESET}"
echo ""
if [ "$MODE" = "vps" ]; then
    echo "  Finish setup in your browser (create your Owner account at /setup):"
    echo "    http://<your-server-ip>:${PORT}/"
    echo ""
    echo "  Manage service:"
    echo "    onx status | start | stop | restart | logs | update"
else
    echo "  Launch from your application menu ('ONX Manager') or run:"
    echo "    onx open"
    echo ""
    echo "  Make sure $(dirname "$ONX_BIN") is in your PATH, then visit:"
    echo "    http://127.0.0.1:${PORT}/"
fi
printf "  %s══════════════════════════════════════════════════════%s\n" "${DIM}" "${RESET}"
echo ""
