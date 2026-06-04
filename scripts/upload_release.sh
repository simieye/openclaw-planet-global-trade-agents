#!/bin/bash
# Upload DMG files to GitHub Release v3.1.0
set -e

REPO="simieye/openclaw-planet-global-trade-agents"
TAG="v3.1.0"
DIST_DIR="/Users/hemingwang/CodeBuddy/20260604085004/dist-electron"

echo "=== Uploading DMG assets to GitHub Release $TAG ==="
echo "Start time: $(date)"

# Upload arm64 DMG
echo "[1/2] Uploading arm64 DMG..."
gh release upload "$TAG" \
  --repo "$REPO" \
  --clobber \
  "$DIST_DIR/LobsterPlanet-3.1.0-arm64.dmg" 2>&1
echo "arm64 DMG upload complete: $(date)"

# Upload x64 DMG
echo "[2/2] Uploading x64 DMG..."
gh release upload "$TAG" \
  --repo "$REPO" \
  --clobber \
  "$DIST_DIR/LobsterPlanet-3.1.0-x64.dmg" 2>&1
echo "x64 DMG upload complete: $(date)"

echo "=== All uploads complete ==="
echo "End time: $(date)"
