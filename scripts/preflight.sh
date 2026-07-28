#!/usr/bin/env bash
#
# MC Server Manager — Preflight Process Cleanup
# ==============================================
# Runs BEFORE every backend/frontend start to prevent duplicate processes,
# orphaned services, and stale SQLite locks.  Idempotent — safe to run
# anytime, even on a clean system.
#
# Usage:
#   scripts/preflight.sh          # normal run
#   MCS_PROJECT_ROOT=/custom/path scripts/preflight.sh   # explicit root
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

BACKEND_PORT="${MCS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${MCS_FRONTEND_PORT:-5173}"
PROJECT_ROOT="${MCS_PROJECT_ROOT:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"
BACKEND_DIR="${PROJECT_ROOT}/backend"
MCS_DB="${BACKEND_DIR}/mcs.db"
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
    local cwd cmd

    # Check /proc/<PID>/cwd  (most reliable)
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

    # Check /proc/<PID>/cmdline (fallback — port listeners often lose cwd)
    if [ -r "/proc/${pid}/cmdline" ]; then
        cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
        if [[ -z "$cmd" ]]; then
            return 1
        fi
        # Match any of: project dir, mcs-frontend, mcs-manager, backend app path
        if [[ "$cmd" == *"${PROJECT_ROOT}"* ]] &&
           [[ "$cmd" != *"${PROJECT_ROOT}/backend/data/servers/"* ]]; then
            return 0
        fi
        if [[ "$cmd" == *"mcs-frontend"* ]] ||
           [[ "$cmd" == *"mcs-manager"* ]] ||
           [[ "$cmd" == *"app.main:app"* ]] ||
           [[ "$cmd" == *"npm"* ]]; then
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

kill_safe() {
    local pid="$1"
    local source_desc="$2"
    local killed=false

    if ! kill -0 "${pid}" 2>/dev/null; then
        return 0  # already gone
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
    killed=true

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
# Checks
# ──────────────────────────────────────────────────────────────────────

check_port() {
    local port="$1"
    local label="$2"
    local pids
    pids="$(lsof -ti "tcp:${port}" 2>/dev/null || true)"
    if [ -z "${pids}" ]; then
        return 0
    fi
    for pid in ${pids}; do
        pid="$(echo "${pid}" | tr -d '[:space:]')"
        [ -z "${pid}" ] && continue
        kill_safe "${pid}" "${label} port ${port}" || true
    done
}

# Remove stale PID files from .mcs/ after killing matching processes
# This prevents launcher.py from reading a dead PID on next startup.
cleanup_pid_files() {
    local mcs_dir="${PROJECT_ROOT}/.mcs"
    if [ ! -d "${mcs_dir}" ]; then
        return 0
    fi

    local cleaned=0
    for pid_file in "${mcs_dir}"/*.pid; do
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
        log_info "Cleaned ${cleaned} stale PID file(s) from .mcs/"
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
        kill_safe "${pid}" "SQLite lock on ${db_path}" || true
    done
}

scan_orphans() {
    # Scan for project-related processes that may not hold a port or db lock.
    # Uses ps with command matching (broader net, the belongs_to_project check
    # will filter out false positives).
    local patterns=("uvicorn" "vite" "node.*mcs-frontend" "python.*main:app" "npm")
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
               [[ "${cmdline}" != *"mcs-frontend"* ]] &&
               [[ "${cmdline}" != *"mcs-manager"* ]] &&
               [[ "${cmdline}" != *"app.main:app"* ]] &&
               [[ "${cmdline}" != *"npm"* ]]; then
                continue
            fi

            kill_safe "${pid}" "orphan (${pattern})" || true
        done < <(ps aux | grep -iE "${pattern}" | grep -v grep 2>/dev/null || true)
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
    be_pids="$(lsof -ti "tcp:${BACKEND_PORT}" 2>/dev/null || true)"
    fe_pids="$(lsof -ti "tcp:${FRONTEND_PORT}" 2>/dev/null || true)"
    db_pids="$(lsof -t "${MCS_DB}" 2>/dev/null || true)"

    local any_remaining=false
    [ -n "${be_pids}" ] && any_remaining=true
    [ -n "${fe_pids}" ] && any_remaining=true
    [ -n "${db_pids}" ] && any_remaining=true

    if ! ${FOUND_ANY}; then
        log_ok "Nothing to clean — system was already clean."
    fi

    local port_status
    if [ -n "${be_pids}" ]; then
        port_status="${RED}in use${RESET}"
    else
        port_status="${GREEN}free${RESET}"
    fi
    echo "     ${BOLD}Backend port ${BACKEND_PORT}:${RESET} ${port_status}"

    if [ -n "${fe_pids}" ]; then
        port_status="${RED}in use${RESET}"
    else
        port_status="${GREEN}free${RESET}"
    fi
    echo "     ${BOLD}Frontend port ${FRONTEND_PORT}:${RESET} ${port_status}"

    if [ -n "${db_pids}" ]; then
        port_status="${RED}locked${RESET}"
    else
        port_status="${GREEN}free${RESET}"
    fi
    echo "     ${BOLD}SQLite DB:${RESET} ${port_status}"

    echo ""

    if ${any_remaining}; then
        log_error "Preflight FAILED — cannot guarantee clean state."
        log_raw ""
        return 1
    fi

    if ${KILLED_ANY}; then
        log_ok "Preflight complete — cleaned ${#SUMMARY_LINES[@]} item(s)."
    else
        log_ok "System is clean. Proceed."
    fi
    log_raw ""
    return 0
}

# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

main() {
    echo ""
    log_bold "═══ MC Server Manager — Preflight ═══"
    log_dim "Project root: ${PROJECT_ROOT}"
    echo ""

    check_port "${BACKEND_PORT}"  "backend"
    check_port "${FRONTEND_PORT}" "frontend"
    check_db_lock "${MCS_DB}"
    scan_orphans

    # Clean stale .mcs/*.pid files after killing matching processes
    cleanup_pid_files

    print_summary
    local rc=$?

    if [ "${rc}" -ne 0 ] || ${FAILED_ANY}; then
        exit 1
    fi
    exit 0
}

main "$@"
