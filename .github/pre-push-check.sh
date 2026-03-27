#!/bin/bash
# Pre-push check: ensure no project-specific content in public repo
# Install: cp .github/pre-push-check.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push

echo "Checking for project-specific content in public repo..."
FOUND=0

# Files being pushed (diff against remote main)
FILES=$(git diff origin/main..HEAD --name-only 2>/dev/null)
if [ -z "$FILES" ]; then
  echo "OK: No new files to check."
  exit 0
fi

# Exclude this script from checks (it contains patterns as search strings)
EXCLUDE=".github/pre-push-check.sh"
CHECK_FILES=$(echo "$FILES" | grep -v "$EXCLUDE")

if [ -z "$CHECK_FILES" ]; then
  echo "OK: Only hook script changed."
  exit 0
fi

# Block project-specific paths and content
# Patterns are split to avoid self-matching
P1="DP""Spice-com"
P2="dynamic""-phasors"
P3="dpspice""\\.com"
for pattern in "$P1" "$P2" "$P3"; do
  MATCHES=$(echo "$CHECK_FILES" | xargs grep -l "$pattern" 2>/dev/null)
  if [ -n "$MATCHES" ]; then
    echo "BLOCKED: Found '$pattern' in:"
    echo "$MATCHES" | sed 's/^/  /'
    FOUND=1
  fi
done

# Block project-specific filenames
for f in $CHECK_FILES; do
  case "$(basename "$f")" in
    *dpspice*|*DPSpice*|*DPSPICE*)
      echo "BLOCKED: Project-specific filename: $f"
      FOUND=1
      ;;
  esac
done

if [ $FOUND -eq 1 ]; then
  echo ""
  echo "Project-specific content must not be in the public claude-handler repo."
  echo "Move to my-world (private) or the project repo instead."
  echo "To bypass (emergency only): git push --no-verify"
  exit 1
fi
echo "OK: No project-specific content found."
