#!/bin/bash
# fleet-diagnose.sh — Look up and optionally run diagnosis for a fleet error code.
#
# Usage:
#   ./fleet-diagnose.sh D-013          # Print diagnosis + fix for D-013
#   ./fleet-diagnose.sh D-013 --run    # Print AND run the diagnosis commands
#   ./fleet-diagnose.sh --list         # List all error codes
#   ./fleet-diagnose.sh --recent       # Show last 10 errors from daemon-errors.log

set -uo pipefail

FLEET_DIR="$HOME/.claude-fleet"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNBOOK="$SCRIPT_DIR/../RUNBOOK.md"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

if [[ ! -f "$RUNBOOK" ]]; then
    echo -e "${RED}RUNBOOK.md not found at $RUNBOOK${NC}" >&2
    exit 1
fi

usage() {
    echo "Usage: $(basename "$0") <error-code> [--run]"
    echo "       $(basename "$0") --list"
    echo "       $(basename "$0") --recent [N]"
    echo ""
    echo "Examples:"
    echo "  $(basename "$0") D-013          # Show diagnosis for D-013"
    echo "  $(basename "$0") D-013 --run    # Show and run diagnosis commands"
    echo "  $(basename "$0") --list         # List all error codes"
    echo "  $(basename "$0") --recent 20    # Show last 20 errors"
}

list_codes() {
    echo -e "${BOLD}Fleet Error Codes${NC}"
    echo ""
    # Extract the quick reference table from RUNBOOK.md
    awk '/^## Quick Reference/,/^---/' "$RUNBOOK" | grep '^| D-' | while IFS='|' read -r _ code severity category desc recovery _; do
        code=$(echo "$code" | xargs)
        severity=$(echo "$severity" | xargs)
        desc=$(echo "$desc" | xargs)
        case "$severity" in
            critical) color="$RED" ;;
            warning)  color="$YELLOW" ;;
            info)     color="$GREEN" ;;
            *)        color="$NC" ;;
        esac
        printf "  ${color}%-7s${NC} %-8s %s\n" "$code" "[$severity]" "$desc"
    done
}

recent_errors() {
    local count="${1:-10}"
    local error_log="$FLEET_DIR/daemon-errors.log"
    if [[ ! -f "$error_log" ]]; then
        echo -e "${YELLOW}No error log found at $error_log${NC}"
        return 0
    fi
    echo -e "${BOLD}Last $count errors:${NC}"
    echo ""
    tail -"$count" "$error_log" | while IFS= read -r line; do
        if [[ "$line" == *"[D-0"* ]]; then
            # Daemon/PID errors
            echo -e "  ${RED}$line${NC}"
        elif [[ "$line" == *"[D-01"* ]]; then
            # Task errors
            echo -e "  ${YELLOW}$line${NC}"
        elif [[ "$line" == *"[D-05"* ]]; then
            # System errors
            echo -e "  ${YELLOW}$line${NC}"
        else
            echo "  $line"
        fi
    done
}

lookup_code() {
    local code="$1"
    local run_mode="${2:-}"

    # Normalize code format (accept d-013, D013, D-013)
    code=$(echo "$code" | tr '[:lower:]' '[:upper:]')
    [[ "$code" =~ ^D[0-9] ]] && code="D-${code:1}"

    # Extract the section for this code from RUNBOOK.md
    local section
    section=$(awk "/^## $code:/,/^## D-[0-9]/" "$RUNBOOK" | sed '$d')

    if [[ -z "$section" ]]; then
        # Try the last section (no next section to delimit)
        section=$(awk "/^## $code:/" "$RUNBOOK" | head -1)
        if [[ -z "$section" ]]; then
            echo -e "${RED}Error code $code not found in RUNBOOK.md${NC}" >&2
            echo ""
            echo "Available codes:"
            grep '^## D-' "$RUNBOOK" | sed 's/## /  /'
            return 1
        fi
        section=$(awk "/^## $code:/,0" "$RUNBOOK")
    fi

    echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}"
    echo -e "${BOLD}  $code${NC}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}"
    echo ""
    echo "$section" | sed 's/^## .*//' | sed '/^$/N;/^\n$/d'

    if [[ "$run_mode" == "--run" ]]; then
        echo ""
        echo -e "${BOLD}${YELLOW}═══ Running diagnosis commands ═══${NC}"
        echo ""

        # Extract bash commands from the Diagnosis section
        local in_diagnosis=false
        local in_code_block=false

        echo "$section" | while IFS= read -r line; do
            if [[ "$line" == "### Diagnosis" ]]; then
                in_diagnosis=true
                continue
            fi
            if [[ "$in_diagnosis" == true && "$line" == "### "* ]]; then
                break
            fi
            if [[ "$in_diagnosis" == true ]]; then
                if [[ "$line" == '```bash' || "$line" == '```sh' ]]; then
                    in_code_block=true
                    continue
                fi
                if [[ "$line" == '```' && "$in_code_block" == true ]]; then
                    in_code_block=false
                    continue
                fi
                if [[ "$in_code_block" == true && -n "$line" && "$line" != \#* ]]; then
                    echo -e "${BLUE}\$ $line${NC}"
                    eval "$line" 2>&1 | sed 's/^/  /'
                    echo ""
                fi
            fi
        done
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

case "$1" in
    --list|-l)
        list_codes
        ;;
    --recent|-r)
        recent_errors "${2:-10}"
        ;;
    --help|-h)
        usage
        ;;
    D-*|d-*)
        lookup_code "$1" "${2:-}"
        ;;
    *)
        echo -e "${RED}Unknown argument: $1${NC}" >&2
        usage
        exit 1
        ;;
esac
