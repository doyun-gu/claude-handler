#!/bin/bash
# merge-worker-prs.sh — Sequentially rebase and merge all open worker PRs
#
# Usage:
#   ./merge-worker-prs.sh                    # Merge all open worker/* PRs
#   ./merge-worker-prs.sh --repo owner/repo  # Specify repo
#   ./merge-worker-prs.sh --dry-run          # Show what would be merged
#
# Handles the cascade conflict problem: after merging PR #1, PR #2's base
# is stale. This script rebases each PR onto latest main before merging.

set -uo pipefail

REPO="${REPO:-}"
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --repo) shift; REPO="$1"; shift ;;
        --repo=*) REPO="${arg#*=}" ;;
        --dry-run) DRY_RUN=true ;;
    esac
done

# Auto-detect repo from git remote if not specified
if [[ -z "$REPO" ]]; then
    REPO=$(git remote get-url origin 2>/dev/null | sed 's/.*github.com[:/]\(.*\)\.git/\1/' | sed 's/.*github.com[:/]\(.*\)/\1/')
    if [[ -z "$REPO" ]]; then
        echo "ERROR: Cannot detect repo. Use --repo owner/name"
        exit 1
    fi
fi

echo "Repository: $REPO"
echo ""

# Get all open worker PRs, sorted by number (oldest first)
PRS=$(gh pr list --repo "$REPO" --search "head:worker/" --state open \
    --json number,title,headRefName --jq 'sort_by(.number) | .[] | "\(.number)\t\(.headRefName)\t\(.title)"' 2>/dev/null)

if [[ -z "$PRS" ]]; then
    echo "No open worker PRs found."
    exit 0
fi

TOTAL=$(echo "$PRS" | wc -l | tr -d ' ')
echo "Found $TOTAL open worker PRs"
echo ""

MERGED=0
FAILED=0
SKIPPED=0

while IFS=$'\t' read -r PR_NUM BRANCH TITLE; do
    echo "--- PR #$PR_NUM: $TITLE ---"
    echo "    Branch: $BRANCH"

    if $DRY_RUN; then
        echo "    [dry-run] Would rebase and merge"
        echo ""
        continue
    fi

    # Check if PR is mergeable
    MERGEABLE=$(gh pr view "$PR_NUM" --repo "$REPO" --json mergeable --jq '.mergeable' 2>/dev/null)

    if [[ "$MERGEABLE" == "MERGEABLE" ]]; then
        # Already clean -- merge directly
        if gh pr merge "$PR_NUM" --repo "$REPO" --squash --delete-branch 2>/dev/null; then
            echo "    Merged (clean)"
            MERGED=$((MERGED + 1))
        else
            echo "    FAILED to merge"
            FAILED=$((FAILED + 1))
        fi
    elif [[ "$MERGEABLE" == "CONFLICTING" ]]; then
        # Needs rebase -- try via GitHub API first
        echo "    Conflicting -- attempting rebase..."
        if gh api "repos/$REPO/pulls/$PR_NUM/update-branch" \
            -X PUT -f update_method=rebase 2>/dev/null; then
            echo "    Rebased via API"
            sleep 3  # wait for GitHub to update mergeable state

            if gh pr merge "$PR_NUM" --repo "$REPO" --squash --delete-branch 2>/dev/null; then
                echo "    Merged (after rebase)"
                MERGED=$((MERGED + 1))
            else
                echo "    FAILED to merge after rebase"
                FAILED=$((FAILED + 1))
            fi
        else
            echo "    API rebase failed -- skipping (needs manual resolution)"
            SKIPPED=$((SKIPPED + 1))
        fi
    else
        echo "    Mergeable state: $MERGEABLE -- waiting..."
        # Unknown/checking state -- wait and retry once
        sleep 5
        if gh pr merge "$PR_NUM" --repo "$REPO" --squash --delete-branch 2>/dev/null; then
            echo "    Merged (after wait)"
            MERGED=$((MERGED + 1))
        else
            echo "    SKIPPED (state: $MERGEABLE)"
            SKIPPED=$((SKIPPED + 1))
        fi
    fi

    # Brief pause between merges to let GitHub update main
    sleep 2
    echo ""
done <<< "$PRS"

echo "================================"
echo "Results: $MERGED merged, $FAILED failed, $SKIPPED skipped (of $TOTAL)"
echo "================================"
