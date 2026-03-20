#!/bin/bash
# Fleet Dashboard — starts FastAPI server on port 3003
export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH
cd "$(dirname "$0")"

# Ensure uvicorn + fastapi are available
if ! python3 -c "import uvicorn, fastapi" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install fastapi uvicorn --quiet
fi

echo "Starting Fleet Dashboard on http://0.0.0.0:3003"
exec python3 -m uvicorn api:app --host 0.0.0.0 --port 3003 --reload
