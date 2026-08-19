#!/usr/bin/env bash
# Deploy RoboFleet to Fly.io (Docker + WebSocket, always-on demo).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.fly/bin:${PATH}"

if ! command -v flyctl >/dev/null 2>&1; then
  echo "Installing flyctl..."
  curl -L https://fly.io/install.sh | sh
  export PATH="${HOME}/.fly/bin:${PATH}"
fi

if ! flyctl auth whoami >/dev/null 2>&1; then
  echo "Log in to Fly (browser will open)..."
  flyctl auth login
fi

cd "$ROOT"

if ! flyctl apps list 2>/dev/null | grep -q 'robofleet-dipxk'; then
  echo "Creating app robofleet-dipxk (first time only)..."
  flyctl apps create robofleet-dipxk --org personal 2>/dev/null || flyctl launch --no-deploy --copy-config --name robofleet-dipxk --yes
fi

echo "Deploying..."
flyctl deploy --remote-only

echo ""
echo "Live URL:"
flyctl status --url 2>/dev/null || echo "  https://robofleet-dipxk.fly.dev"
flyctl open 2>/dev/null || true
