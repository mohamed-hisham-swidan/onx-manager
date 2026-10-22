#!/usr/bin/env bash
#
# onx-manager — Preflight Process Cleanup
# ======================================
# Runs BEFORE every backend/frontend start to prevent duplicate processes,
# orphaned services, and stale SQLite locks.  Idempotent — safe to run
# anytime, even on a clean system.
#
# Usage:
#   scripts/preflight.sh          # normal run
#   ONX_PROJECT_ROOT=/custom/path scripts/preflight.sh   # explicit root
#
# On success: exits 0 (system clean or cleaned).
# On failure: exits 1 (something unclean could not be resolved).
#
# ----------------------------------------------------------------------
# WHY THIS EXISTS
# ----------------------------------------------------------------------
# We hit a real incident (see docs/DEVELOPMENT.md §Preflight) where a
# nohup uvicorn process outlived its parent shell and a second backend
# was launched on top of it, causing two processes fighting over the
# same SQLite database file.  This script is the permanent fix.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

FRONTEND_PORT="${ONX_FRONTEND_PORT:-${MCS_FRONTEND_PORT:-5173}}"
PROJECT_ROOT="${ONX_PROJECT_ROOT:-${MCS_PROJECT_ROOT:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}}"

is_valid_port() {
    [[ "${1:-}" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

# Preferred backend port validator (1024..65535, ASCII digits, optional sign, whitespace stripped)
# Unavoidable difference from Python: bash uses sed for config JSON rather than a full JSON parser.
is_valid_preferred_port() {
    local raw="${1:-}"
    local val="${raw#"${raw%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    [[ -n "${val}" ]] || return 1
    ( LC_ALL=C; [[ "${val}" =~ ^[+-]?[0-9]+$ ]] ) || return 1
    [[ "${val}" =~ ^- ]] && return 1
    val="${val#+}"
    local stripped="${val#"${val%%[!0]*}"}"
    [ -n "${stripped}" ] || return 1
    [ "${#stripped}" -le 5 ] || return 1
    local num=$(( 10#${val} ))
    [ "$num" -ge 1024 ] && [ "$num" -le 65535 ]
}

normalize_preferred_port() {
    local raw="${1:-}"
    local val="${raw#"${raw%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    val="${val#+}"
    printf '%s' "$(( 10#${val} ))"
}

read_config_backend_port() {
    local cfg="${1:-${PROJECT_ROOT}/.onx/config.json}"
    [ -f "${cfg}" ] || return 1
    local raw=""
    raw="$(sed -nE 's/.*"backend_port"[[:space:]]*:[[:space:]]*([^,}]+).*/\1/p' "${cfg}" | tail -n 1 | tr -d '"' | tr -d '[:space:]')"
    [ -n "${raw}" ] || return 1
    printf '%s' "${raw}"
}

resolve_preferred_backend_port() {
    local cfg_file="${1:-${PROJECT_ROOT}/.onx/config.json}"
    local val=""

    # 1. ONX_BACKEND_PORT
    if [ "${ONX_BACKEND_PORT+set}" = "set" ]; then
        val="${ONX_BACKEND_PORT}"
        if is_valid_preferred_port "${val}"; then
            normalize_preferred_port "${val}"
            return 0
        else
            echo "Invalid ONX_BACKEND_PORT='${val}'; must be an integer between 1024 and 65535." >&2
        fi
    fi

    # 2. MCS_BACKEND_PORT
    if [ "${MCS_BACKEND_PORT+set}" = "set" ]; then
        val="${MCS_BACKEND_PORT}"
        if is_valid_preferred_port "${val}"; then
            normalize_preferred_port "${val}"
            return 0
        else
            echo "Invalid MCS_BACKEND_PORT='${val}'; must be an integer between 1024 and 65535." >&2
        fi
    fi

    # 3. .onx/config.json
    if val="$(read_config_backend_port "${cfg_file}")"; then
        if is_valid_preferred_port "${val}"; then
            normalize_preferred_port "${val}"
            return 0
        else
            echo "Invalid config backend_port=${val}; must be an integer between 1024 and 65535." >&2
        fi
    fi

    # 4. Fallback default
    printf '%s' "8000"
    return 0
}

BACKEND_PORT="$(resolve_preferred_backend_port)"

ACTIVE_BACKEND_PORT=""
for _port_file in "${PROJECT_ROOT}/.onx/backend.port" "${PROJECT_ROOT}/.mcs/backend.port"; do
    if [ -f "${_port_file}" ]; then
        _active="$(head -n 1 "${_port_file}" 2>/dev/null | tr -d '[:space:]' || true)"
        if is_valid_port "${_active}"; then
            ACTIVE_BACKEND_PORT="${_active}"
            break
        fi
    fi
done
if [ -n "${ACTIVE_BACKEND_PORT}" ] && ! lsof -ti "tcp:${ACTIVE_BACKEND_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    ACTIVE_BACKEND_PORT=""
fi

BACKEND_DIR="${PROJECT_ROOT}/backend"
ONX_DB="${ONX_DB_PATH:-${BACKEND_DIR}/data/onx.db}"
KILL_WAIT=5
BOLD=""
DIM=""
GREEN=""
YELLOW=""
RED=""
RESET=""

# Colours — enabled automatically when stdout is a terminal
if [ -t 1 ]; then
    BOLD="$(printf '\033[1m')"
    DIM="$(printf '\033[2m')"
    GREEN="$(printf '\033[92m')"
    YELLOW="$(printf '\033[93m')"
    RED="$(printf '\033[91m')"
    RESET="$(printf '\033[0m')"
fi

# ──────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────

FOUND_ANY=false
KILLED_ANY=false
FAILED_ANY=false
SUMMARY_LINES=()

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

log_info()  { echo "  ${DIM}▪${RESET} $*"; }
log_warn()  { echo "  ${YELLOW}⚠${RESET} $*"; }
log_ok()    { echo "  ${GREEN}✔${RESET} $*"; }
log_error() { echo "  ${RED}✖${RESET} $*"; }
log_bold()  { echo "${BOLD}$*${RESET}"; }
log_dim()   { echo "${DIM}$*${RESET}"; }
log_raw()   { echo "$*"; }

# ──────────────────────────────────────────────────────────────────────
# Belongs-to-project check
# ──────────────────────────────────────────────────────────────────────

# Return 0 if the PID clearly belongs to this project, 1 otherwise.
# Uses three signals:
#   1. /proc/<PID>/cwd  → should be under PROJECT_ROOT
#   2. /proc/<PID>/cmdline  → should contain a project keyword
#   3. Port-based processes may not have a cwd readable by us,
#      so we also check the command string.
belongs_to_project() {
    local pid="$1"
    local cwd="" cmd=""

    # Check cmdline first to exclude background daemons & games
    if [ -r "/proc/${pid}/cmdline" ]; then
        cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
        if [[ "$cmd" == *"playit"* ]] ||
           [[ "$cmd" == *"cloudflared"* ]] ||
           [[ "$cmd" == *"tmux"* ]] ||
           [[ "$cmd" == *"java"* ]]; then
            return 1
        fi
    fi

    # Check /proc/<PID>/cwd
    if [ -L "/proc/${pid}/cwd" ]; then
        cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
        if [[ "$cwd" == "${PROJECT_ROOT}"* ]]; then
            # Exclude server data directories — these are live Minecraft servers
            if [[ "$cwd" == "${PROJECT_ROOT}/backend/data/servers/"* ]]; then
                return 1
            fi
            return 0
        fi
    fi

    # Check /proc/<PID>/cmdline (strict project markers only — do NOT match generic 'uvicorn' or 'npm')
    if [ -n "$cmd" ]; then
        # Match project root path (excluding server data directories)
        if [[ "$cmd" == *"${PROJECT_ROOT}"* ]] &&
           [[ "$cmd" != *"${PROJECT_ROOT}/backend/data/servers/"* ]]; then
            return 0
        fi
        # Match specific unique project identifiers
        if [[ "$cmd" == *"onx-frontend"* ]] ||
           [[ "$cmd" == *"mcs-frontend"* ]] ||
           [[ "$cmd" == *"onx-manager"* ]] ||
           [[ "$cmd" == *"mcs-manager"* ]] ||
           [[ "$cmd" == *"app.main:app"* ]]; then
            return 0
        fi
    fi

    return 1
}

# ──────────────────────────────────────────────────────────────────────
# Kill helpers
# ──────────────────────────────────────────────────────────────────────

print_process() {
    local pid="$1"
    local label="${2:-}"
    local header="${label:+(process ${label}) }"
    log_raw "       PID ${pid}  $(ps -p "${pid}" -o pid,ppid,cmd --no-headers 2>/dev/null || echo '(unreadable)')"
}

is_caller_or_ancestor() {
    local target="$1"
    [ -z "$target" ] && return 1
    if [ "$target" = "$$" ]; then
        return 0
    fi
    local curr="$$"
    while [ -n "$curr" ] && [ "$curr" -gt 1 ]; do
        if [ "$curr" = "$target" ]; then
            return 0
        fi
        curr="$(ps -o ppid= -p "$curr" 2>/dev/null || true)"
        curr="$(echo "$curr" | tr -d '[:space:]')"
    done
    return 1
}

kill_safe() {
    local pid="$1"
    local source_desc="$2"

    if ! kill -0 "${pid}" 2>/dev/null; then
        return 0  # already gone
    fi

    if is_protected "${pid}"; then
        log_info "PID ${pid} (${source_desc}) is protected — preserved"
        return 0
    fi

    if is_caller_or_ancestor "${pid}"; then
        log_info "PID ${pid} is caller/ancestor of preflight script — preserved"
        return 0
    fi

    if ! belongs_to_project "${pid}"; then
        log_warn "PID ${pid} ($source_desc) does NOT appear to belong to this project."
        log_warn "Printing details for manual review — will NOT kill:"
        print_process "${pid}"
        SUMMARY_LINES+=("${YELLOW}⚠${RESET} PID ${pid}  ${source_desc}  skipped (unknown owner)${RESET}")
        return 1
    fi

    log_info "Killing PID ${pid} (${source_desc})..."
    print_process "${pid}"
    FOUND_ANY=true

    kill "${pid}" 2>/dev/null || true

    # Wait up to KILL_WAIT seconds
    local waited=0
    while kill -0 "${pid}" 2>/dev/null && [ "${waited}" -lt "${KILL_WAIT}" ]; do
        sleep 1
        waited=$((waited + 1))
    done

    # Force if still alive
    if kill -0 "${pid}" 2>/dev/null; then
        log_warn "PID ${pid} did not respond to SIGTERM after ${KILL_WAIT}s — sending SIGKILL"
        kill -9 "${pid}" 2>/dev/null || true
        sleep 1
    fi

    if kill -0 "${pid}" 2>/dev/null; then
        log_error "Failed to kill PID ${pid} even with SIGKILL"
        FAILED_ANY=true
        SUMMARY_LINES+=("${RED}✖${RESET} PID ${pid}  ${source_desc}  ${RED}could not kill${RESET}")
        return 1
    fi

    KILLED_ANY=true
    SUMMARY_LINES+=("${RED}✖${RESET} PID ${pid}  ${source_desc}  ${GREEN}killed${RESET}")
    return 0
}

# ──────────────────────────────────────────────────────────────────────
# Protection & Health State
# ──────────────────────────────────────────────────────────────────────

PROTECTED_PIDS=()
FORCE_CLEAN=false

is_protected() {
    local target="$1"
    [ -z "$target" ] && return 1
    if is_caller_or_ancestor "$target"; then
        return 0
    fi
    for p in "${PROTECTED_PIDS[@]}"; do
        if [ "$p" = "$target" ]; then
            return 0
        fi
    done
    return 1
}

protect_family() {
    local base_pid="$1"
    [ -z "$base_pid" ] && return

    if ! is_protected "$base_pid"; then
        PROTECTED_PIDS+=("$base_pid")
    fi

    # Add child processes (e.g. uvicorn reload child / worker / node threads)
    local children
    children="$(pgrep -P "$base_pid" 2>/dev/null || true)"
    for c in $children; do
        c="$(echo "$c" | tr -d '[:space:]')"
        if [ -n "$c" ] && ! is_protected "$c"; then
            PROTECTED_PIDS+=("$c")
        fi
    done

    # Add project-owned ancestors (terminal wrapper, shell, etc.)
    local ppid
    ppid="$(ps -o ppid= -p "$base_pid" 2>/dev/null || true)"
    ppid="$(echo "$ppid" | tr -d '[:space:]')"
    while [ -n "$ppid" ] && [ "$ppid" -gt 1 ] && belongs_to_project "$ppid"; do
        if ! is_protected "$ppid"; then
            PROTECTED_PIDS+=("$ppid")
        fi
        ppid="$(ps -o ppid= -p "$ppid" 2>/dev/null || true)"
        ppid="$(echo "$ppid" | tr -d '[:space:]')"
    done
}

is_backend_healthy() {
    local port="${1:-${BACKEND_PORT}}"
    command -v curl &>/dev/null || return 1
    local body
    body="$(curl -fsS --max-time 2 "http://127.0.0.1:${port}/health" 2>/dev/null || true)"
    [ -n "${body}" ] || return 1
    printf '%s' "${body}" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' || return 1
    printf '%s' "${body}" | grep -Eq '"version"[[:space:]]*:' || return 1
    return 0
}

is_listening_on() {
    local pid="$1" port="$2"
    lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null | tr '[:space:]' '\n' | grep -qx "${pid}"
}

port_is_open() {
    local port="$1"
    (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null || return 1
    exec 3>&-
    return 0
}

is_frontend_healthy() {
    if command -v curl &>/dev/null; then
        local code
        code="$(curl -s -o /dev/null -w "%{http_code}" -m 2 "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null || true)"
        if [ "$code" = "200" ] || [ "$code" = "304" ] || [ "$code" = "302" ]; then
            return 0
        fi
    fi
    return 1
}

# ──────────────────────────────────────────────────────────────────────
# Checks
# ──────────────────────────────────────────────────────────────────────

check_services() {
    # 1. Active backend port (may differ from preferred)
    if [ -n "${ACTIVE_BACKEND_PORT}" ] && [ "${ACTIVE_BACKEND_PORT}" != "${BACKEND_PORT}" ]; then
        local active_pids
        active_pids="$(lsof -ti "tcp:${ACTIVE_BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
        for pid in ${active_pids}; do
            pid="$(echo "${pid}" | tr -d '[:space:]')"
            [ -z "${pid}" ] && continue
            if [ "${FORCE_CLEAN}" = "false" ] && is_backend_healthy "${ACTIVE_BACKEND_PORT}"; then
                protect_family "${pid}"
                log_ok "Active backend on port ${ACTIVE_BACKEND_PORT} (PID ${pid}) — preserving"
                SUMMARY_LINES+=("${GREEN}✔${RESET} Backend  PID ${pid} (port ${ACTIVE_BACKEND_PORT})  ${GREEN}active & healthy${RESET}")
            elif belongs_to_project "${pid}"; then
                kill_safe "${pid}" "unhealthy backend on active port ${ACTIVE_BACKEND_PORT}" || true
            else
                log_warn "Active-port listener ${pid} is foreign — leaving untouched"
            fi
        done
    fi

    # 2. Preferred backend port
    local be_pids
    be_pids="$(lsof -ti "tcp:${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "${be_pids}" ]; then
        if [ "${FORCE_CLEAN}" = "false" ] && is_backend_healthy "${BACKEND_PORT}"; then
            for pid in ${be_pids}; do
                pid="$(echo "${pid}" | tr -d '[:space:]')"
                [ -z "${pid}" ] && continue
                if belongs_to_project "${pid}"; then
                    protect_family "${pid}"
                    log_ok "Healthy backend running on port ${BACKEND_PORT} (PID ${pid}) — preserving"
                    SUMMARY_LINES+=("${GREEN}✔${RESET} Backend  PID ${pid} (port ${BACKEND_PORT})  ${GREEN}active & healthy${RESET}")
                else
                    log_warn "Port ${BACKEND_PORT} is held by a foreign service (PID ${pid}); launcher will use another port"
                fi
            done
        else
            for pid in ${be_pids}; do
                pid="$(echo "${pid}" | tr -d '[:space:]')"
                [ -z "${pid}" ] && continue
                if belongs_to_project "${pid}" || [ "${FORCE_CLEAN}" = "true" ]; then
                    kill_safe "${pid}" "backend port ${BACKEND_PORT}" || true
                else
                    log_warn "Port ${BACKEND_PORT} is held by a foreign service (PID ${pid}); leaving untouched"
                fi
            done
        fi
    fi

    # 2. Frontend Port (5173)
    local fe_pids
    fe_pids="$(lsof -ti "tcp:${FRONTEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "${fe_pids}" ]; then
        if [ "${FORCE_CLEAN}" = "false" ] && is_frontend_healthy; then
            for pid in ${fe_pids}; do
                pid="$(echo "${pid}" | tr -d '[:space:]')"
                [ -z "${pid}" ] && continue
                protect_family "${pid}"
                log_ok "Healthy frontend running on port ${FRONTEND_PORT} (PID ${pid}) — preserving"
                SUMMARY_LINES+=("${GREEN}✔${RESET} Frontend PID ${pid} (port ${FRONTEND_PORT})  ${GREEN}active & healthy${RESET}")
            done
        else
            for pid in ${fe_pids}; do
                pid="$(echo "${pid}" | tr -d '[:space:]')"
                [ -z "${pid}" ] && continue
                kill_safe "${pid}" "frontend port ${FRONTEND_PORT}" || true
            done
        fi
    fi
}

check_db_lock() {
    local db_path="$1"
    if [ ! -f "${db_path}" ]; then
        return 0
    fi
    local pids
    pids="$(lsof -t "${db_path}" 2>/dev/null || true)"
    if [ -z "${pids}" ]; then
        return 0
    fi
    for pid in ${pids}; do
        pid="$(echo "${pid}" | tr -d '[:space:]')"
        [ -z "${pid}" ] && continue
        if is_protected "${pid}"; then
            log_info "SQLite lock on database held by active backend (PID ${pid}) — preserved"
            continue
        fi

        # Scope kill predicate to an actual server-process signature:
        # Require cmdline to match uvicorn or app.main:app AND not match pytest/xdist/py.test
        local cmd=""
        if [ -r "/proc/${pid}/cmdline" ]; then
            cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
        fi
        if [ -z "$cmd" ]; then
            cmd="$(ps -p "${pid}" -o cmd= 2>/dev/null || true)"
        fi

        if [[ "$cmd" == *"pytest"* ]] || [[ "$cmd" == *"xdist"* ]] || [[ "$cmd" == *"py.test"* ]]; then
            protect_family "${pid}"
            log_info "SQLite lock on database held by test worker (PID ${pid}) — preserved"
            continue
        fi

        if [[ "$cmd" != *"uvicorn"* ]] && [[ "$cmd" != *"app.main:app"* ]]; then
            log_info "SQLite lock on database held by non-server process (PID ${pid}) — preserved"
            continue
        fi

        kill_safe "${pid}" "stale SQLite lock on ${db_path}" || true
    done
}

scan_orphans() {
    # Scan for duplicate / inactive / dead orphan processes that do NOT hold an active port
    local patterns=("uvicorn" "vite" "node.*onx-frontend" "node.*mcs-frontend" "python.*main:app" "npm")
    local seen_pids=""

    for pattern in "${patterns[@]}"; do
        while IFS= read -r line; do
            [ -z "${line}" ] && continue
            local pid
            pid="$(echo "${line}" | awk '{print $2}')"
            pid="$(echo "${pid}" | tr -d '[:space:]')"
            [ -z "${pid}" ] && continue

            # Deduplicate
            if [[ "${seen_pids}" == *" ${pid} "* ]]; then
                continue
            fi
            seen_pids=" ${seen_pids} ${pid} "

            # Never kill protected running services
            if is_protected "${pid}"; then
                continue
            fi

            # Belt-and-braces: never kill a healthy listener on the active or preferred port
            if { [ -n "${ACTIVE_BACKEND_PORT}" ] && is_listening_on "${pid}" "${ACTIVE_BACKEND_PORT}" && is_backend_healthy "${ACTIVE_BACKEND_PORT}"; } ||
               { is_listening_on "${pid}" "${BACKEND_PORT}" && is_backend_healthy "${BACKEND_PORT}"; }; then
                protect_family "${pid}"
                continue
            fi

            # Quick check before expensive belongs_to_project
            local cmdline
            cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
            if [[ -z "${cmdline}" ]]; then
                continue
            fi
            if [[ "${cmdline}" == *"${PROJECT_ROOT}/backend/data/servers/"* ]]; then
                continue
            fi
            if [[ "${cmdline}" != *"${PROJECT_ROOT}"* ]] &&
               [[ "${cmdline}" != *"onx-frontend"* ]] &&
               [[ "${cmdline}" != *"mcs-frontend"* ]] &&
               [[ "${cmdline}" != *"onx-manager"* ]] &&
               [[ "${cmdline}" != *"mcs-manager"* ]] &&
               [[ "${cmdline}" != *"app.main:app"* ]] &&
               [[ "${cmdline}" != *"npm"* ]]; then
                continue
            fi

            kill_safe "${pid}" "inactive/duplicate orphan (${pattern})" || true
        done < <(ps aux | grep -iE "${pattern}" | grep -v grep 2>/dev/null || true)
    done
}

# Remove stale PID files or sync with live protected PIDs
cleanup_pid_files() {
    for dir_name in ".onx" ".mcs"; do
        local pid_dir="${PROJECT_ROOT}/${dir_name}"
        if [ ! -d "${pid_dir}" ]; then
            continue
        fi

        # Sync live PIDs if protected (active port first, then preferred)
        local be_pid="" fe_pid
        if [ -n "${ACTIVE_BACKEND_PORT}" ]; then
            be_pid="$(lsof -ti "tcp:${ACTIVE_BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
        fi
        if [ -z "${be_pid}" ] || ! is_protected "${be_pid}"; then
            be_pid="$(lsof -ti "tcp:${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
        fi
        fe_pid="$(lsof -ti "tcp:${FRONTEND_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"

        if [ -n "${be_pid}" ] && is_protected "${be_pid}"; then
            echo "${be_pid}" > "${pid_dir}/backend.pid" 2>/dev/null || true
        fi
        if [ -n "${fe_pid}" ] && is_protected "${fe_pid}"; then
            echo "${fe_pid}" > "${pid_dir}/frontend.pid" 2>/dev/null || true
        fi

        local cleaned=0
        for pid_file in "${pid_dir}"/*.pid; do
            [ -f "${pid_file}" ] || continue
            local old_pid
            old_pid="$(cat "${pid_file}" 2>/dev/null || true)"
            if [ -z "${old_pid}" ]; then
                rm -f "${pid_file}" 2>/dev/null || true
                cleaned=$((cleaned + 1))
                continue
            fi
            if ! kill -0 "${old_pid}" 2>/dev/null; then
                rm -f "${pid_file}" 2>/dev/null || true
                cleaned=$((cleaned + 1))
            fi
        done

        if [ "${cleaned}" -gt 0 ]; then
            log_info "Cleaned ${cleaned} stale PID file(s) from ${dir_name}/"
        fi
    done
}

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────

print_summary() {
    local line="────────────────────────────────────────────"
    echo ""
    log_dim "${line}"
    log_bold "  Preflight Summary"
    log_dim "${line}"

    if [ "${#SUMMARY_LINES[@]}" -gt 0 ]; then
        for s in "${SUMMARY_LINES[@]}"; do
            echo "  ${s}"
        done
        echo ""
    fi

    # Final port/db re-check
    local be_pids fe_pids db_pids
    be_pids="$(lsof -ti "tcp:${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    fe_pids="$(lsof -ti "tcp:${FRONTEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    db_pids="$(lsof -t "${ONX_DB}" 2>/dev/null || true)"

    local any_unclean=false

    local port_status
    if [ -n "${be_pids}" ]; then
        local first_be
        first_be="$(echo "${be_pids}" | head -n 1 | tr -d '[:space:]')"
        if is_backend_healthy "${BACKEND_PORT}" && belongs_to_project "${first_be}"; then
            port_status="${GREEN}running (healthy)${RESET}"
        elif belongs_to_project "${first_be}"; then
            port_status="${RED}in use (project-owned, unhealthy)${RESET}"
            any_unclean=true
        else
            port_status="${YELLOW}in use (foreign; launcher will use another port)${RESET}"
        fi
    elif port_is_open "${BACKEND_PORT}"; then
        port_status="${YELLOW}in use (foreign/unattributed; launcher will use another port)${RESET}"
    else
        port_status="${GREEN}free${RESET}"
    fi
    echo "     ${BOLD}Backend port ${BACKEND_PORT}:${RESET} ${port_status}"

    if [ -n "${ACTIVE_BACKEND_PORT}" ] && [ "${ACTIVE_BACKEND_PORT}" != "${BACKEND_PORT}" ]; then
        local active_pids active_status
        active_pids="$(lsof -ti "tcp:${ACTIVE_BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
        if [ -n "${active_pids}" ] && is_backend_healthy "${ACTIVE_BACKEND_PORT}"; then
            active_status="${GREEN}running (healthy) on ${ACTIVE_BACKEND_PORT}${RESET}"
        elif [ -n "${active_pids}" ]; then
            active_status="${YELLOW}stale listener on ${ACTIVE_BACKEND_PORT}${RESET}"
        else
            active_status="${DIM}stale (no listener)${RESET}"
        fi
        echo "     ${BOLD}Active backend port:${RESET} ${active_status}"
    fi

    if [ -n "${fe_pids}" ]; then
        local first_fe
        first_fe="$(echo "${fe_pids}" | head -n 1 | tr -d '[:space:]')"
        if is_protected "${first_fe}" || is_frontend_healthy; then
            port_status="${GREEN}running (healthy)${RESET}"
        else
            port_status="${RED}in use (unclean)${RESET}"
            any_unclean=true
        fi
    else
        port_status="${GREEN}free${RESET}"
    fi
    echo "     ${BOLD}Frontend port ${FRONTEND_PORT}:${RESET} ${port_status}"

    if [ -n "${db_pids}" ]; then
        local all_db_protected=true
        for db_p in ${db_pids}; do
            db_p="$(echo "${db_p}" | tr -d '[:space:]')"
            if ! is_protected "${db_p}"; then
                all_db_protected=false
                break
            fi
        done
        if ${all_db_protected}; then
            port_status="${GREEN}active (healthy backend)${RESET}"
        else
            port_status="${RED}locked (stale)${RESET}"
            any_unclean=true
        fi
    else
        port_status="${GREEN}free${RESET}"
    fi
    echo "     ${BOLD}SQLite DB:${RESET} ${port_status}"

    echo ""

    if ${any_unclean}; then
        log_error "Preflight FAILED — cannot guarantee clean state."
        log_raw ""
        return 1
    fi

    if ${KILLED_ANY}; then
        log_ok "Preflight complete — cleaned dead/duplicate item(s)."
        else
        log_ok "System is healthy and ready. Proceed."
    fi
    log_raw ""
    return 0
}

# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

main() {
    for arg in "$@"; do
        case "$arg" in
            --stop|--restart|--force|--clean|-f)
                FORCE_CLEAN=true
                ;;
        esac
    done

    echo ""
    log_bold "═══ onx-manager — Preflight ═══"
    log_dim "Project root: ${PROJECT_ROOT}"
    if ${FORCE_CLEAN}; then
        log_dim "Mode: Force cleanup (stop/restart)"
    else
        log_dim "Mode: Smart reconciliation (preserve healthy, kill stale/duplicate orphans)"
    fi
    echo ""

    check_services
    check_db_lock "${ONX_DB}"
    scan_orphans
    cleanup_pid_files

    print_summary
    local rc=$?

    if [ "${rc}" -ne 0 ] || ${FAILED_ANY}; then
        exit 1
    fi
    exit 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
