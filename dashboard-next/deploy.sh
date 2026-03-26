#!/bin/bash
# Build and deploy the dashboard to ~/.claude-fleet/dashboard-stable/
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
STABLE_DIR="$HOME/.claude-fleet/dashboard-stable"

echo "Building Next.js dashboard..."
cd "$DIR"
npm run build

echo "Deploying to $STABLE_DIR..."
mkdir -p "$STABLE_DIR"

# Copy standalone server
cp -r .next/standalone/* "$STABLE_DIR/" 2>/dev/null || true
cp -r .next/standalone/.next "$STABLE_DIR/" 2>/dev/null || true

# Copy static assets
mkdir -p "$STABLE_DIR/.next/static"
cp -r .next/static/* "$STABLE_DIR/.next/static/"

# Copy public assets if any
if [ -d public ]; then
  cp -r public/* "$STABLE_DIR/public/" 2>/dev/null || true
fi

echo "Done! Start with:"
echo "  cd $STABLE_DIR && PORT=3003 node server.js"
