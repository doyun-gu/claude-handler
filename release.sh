#!/usr/bin/env bash
#
# release.sh — Create a versioned release from the current state.
#
# Usage:
#   ./release.sh           # Release the version in VERSION file
#   ./release.sh 0.6.0     # Override version
#   ./release.sh --dry-run # Preview without committing/tagging/pushing
#
set -euo pipefail

DRY_RUN=false
VERSION=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) VERSION="$arg" ;;
  esac
done

# Read version from file if not provided
if [[ -z "$VERSION" ]]; then
  if [[ ! -f VERSION ]]; then
    echo "Error: VERSION file not found and no version argument provided."
    exit 1
  fi
  VERSION=$(cat VERSION | tr -d '[:space:]')
fi

TAG="v${VERSION}"
DATE=$(date +%Y-%m-%d)

echo "=== Release $TAG ($DATE) ==="

# Sanity checks
if git tag -l "$TAG" | grep -q "$TAG"; then
  echo "Error: Tag $TAG already exists."
  exit 1
fi

if [[ $(git status --porcelain) ]]; then
  echo "Error: Working directory is not clean. Commit or stash changes first."
  exit 1
fi

# Check we're on main
BRANCH=$(git branch --show-current)
if [[ "$BRANCH" != "main" ]]; then
  echo "Warning: You're on branch '$BRANCH', not 'main'."
  read -rp "Continue anyway? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi

# Update CHANGELOG.md: move [Unreleased] entries to [VERSION]
if [[ ! -f CHANGELOG.md ]]; then
  echo "Error: CHANGELOG.md not found."
  exit 1
fi

# Check if there are unreleased entries
if ! grep -q '## \[Unreleased\]' CHANGELOG.md; then
  echo "Error: No [Unreleased] section found in CHANGELOG.md."
  exit 1
fi

# Replace [Unreleased] header content — add new version section after it
# Keep [Unreleased] empty for future changes
sed -i '' "s/## \[Unreleased\]/## [Unreleased]\n\n## [$VERSION] - $DATE/" CHANGELOG.md

# Update the comparison links at the bottom
# Change the [Unreleased] link to point from new version
sed -i '' "s|\[Unreleased\]: \(.*\)/compare/v.*\.\.\.HEAD|[Unreleased]: \1/compare/v${VERSION}...HEAD|" CHANGELOG.md

if $DRY_RUN; then
  echo ""
  echo "[DRY RUN] Would:"
  echo "  1. Update CHANGELOG.md (shown above)"
  echo "  2. Update VERSION to $VERSION"
  echo "  3. Commit: 'release: v$VERSION'"
  echo "  4. Tag: $TAG"
  echo "  5. Push tag and commit"
  echo "  6. Create GitHub release"
  echo ""
  # Revert CHANGELOG changes
  git checkout -- CHANGELOG.md
  exit 0
fi

# Update VERSION file
echo "$VERSION" > VERSION

# Commit
git add CHANGELOG.md VERSION
git commit -m "release: v${VERSION}"

# Tag
git tag -a "$TAG" -m "Release $TAG"

# Push
echo "Pushing commit and tag..."
git push origin "$BRANCH"
git push origin "$TAG"

# Create GitHub release with changelog section as notes
# Extract the changelog section for this version
NOTES=$(awk "/^## \[$VERSION\]/{flag=1; next} /^## \[/{flag=0} flag" CHANGELOG.md)

if command -v gh &>/dev/null; then
  echo "Creating GitHub release..."
  gh release create "$TAG" \
    --title "v${VERSION}" \
    --notes "$NOTES"
  echo ""
  echo "Release created: $(gh release view "$TAG" --json url -q .url)"
else
  echo "gh CLI not found — skipping GitHub release creation."
  echo "Create manually: https://github.com/doyun-gu/claude-handler/releases/new?tag=$TAG"
fi

echo ""
echo "=== Released $TAG ==="
