#!/usr/bin/env bash
#
# onx-manager Unix Launcher — Diagnostic Tracing Wrapper (Linux & macOS)
# =====================================================================
# Wraps start.sh with full transcript recording and bash line-by-line tracing (set -x).
#
# Zero-drift design: Directly executes start.sh with bash -x, ensuring debug tracing
# automatically stays in sync with start.sh without copy-paste code maintenance.
#
# Usage:
#     ./executors/start-debug.sh [args...]
#
# Output:
#     Transcripts are written to: executors/logs/start-debug-<timestamp>.log
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
START_SCRIPT="${REPO_ROOT}/start.sh"

if [ ! -f "$START_SCRIPT" ]; then
    echo "Error: start.sh not found in repository root: ${REPO_ROOT}" >&2
    exit 1
fi

# Ensure logs directory exists
LOGS_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOGS_DIR"

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="${LOGS_DIR}/start-debug-${TIMESTAMP}.log"

# Color helpers
if [ -t 1 ]; then
    YELLOW='\033[1;33m'
    GREEN='\033[1;32m'
    NC='\033[0m'
else
    YELLOW=''
    GREEN=''
    NC=''
fi

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  onx-manager — Tracing Debug Launcher (Unix)${NC}"
echo -e "${YELLOW}========================================${NC}"
echo "  Directory : ${REPO_ROOT}"
echo "  Log File  : ${LOG_FILE}"
echo "  Tracing   : bash -x enabled"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Record header in log
{
    echo "=== onx-manager start-debug session start: $(date) ==="
    echo "Arguments: $*"
    echo "Working directory: ${REPO_ROOT}"
    echo "========================================================"
} >> "$LOG_FILE"

# Execute start.sh with bash -x tracing, streaming live to terminal and logging to file
EXIT_CODE=0
set +e
bash -x "$START_SCRIPT" "$@" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE="${PIPESTATUS[0]}"
set -e

{
    echo ""
    echo "=== onx-manager start-debug session end: $(date) (exit: ${EXIT_CODE}) ==="
} >> "$LOG_FILE"

echo ""
echo -e "  ${GREEN}✔ Debug transcript saved to: ${LOG_FILE}${NC}"
exit "$EXIT_CODE"
