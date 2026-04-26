#!/usr/bin/env bash
# deploy-all.sh — Rebuild and install all TV apps on the Samsung Frame
# Usage: ./deploy-all.sh [SAWSUBE_URL] [TV_ID]
set -e

SAWSUBE_URL="${1:-http://127.0.0.1:8000}"
TV_ID="${2:-1}"
LOG="/tmp/sawsube.log"

echo "=== SAWSUBE deploy-all ==="
echo "  SAWSUBE: $SAWSUBE_URL"
echo "  TV ID:   $TV_ID"
echo ""

# ── Ensure SAWSUBE is running ────────────────────────────────────────────────
if ! curl -sf "$SAWSUBE_URL/api/health" > /dev/null 2>&1; then
  echo "SAWSUBE not reachable — starting it..."
  (cd "$(dirname "$0")" && nohup .venv/bin/python -m backend.main >> "$LOG" 2>&1 &)
  sleep 4
  if ! curl -sf "$SAWSUBE_URL/api/health" > /dev/null 2>&1; then
    echo "ERROR: SAWSUBE failed to start. Check $LOG" >&2
    exit 1
  fi
  echo "SAWSUBE started OK."
else
  echo "SAWSUBE already running."
fi
echo ""

# ── Deploy Fieshzen ──────────────────────────────────────────────────────────
echo "→ [1/2] Building + installing Fieshzen (music player)..."
R=$(curl -sf -X POST "$SAWSUBE_URL/api/tizenbrew/$TV_ID/build-install-fieshzen")
echo "  Job: $(echo "$R" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job_id','?'))" 2>/dev/null)"
echo ""

# Wait for Fieshzen to complete before starting Radarrzen
echo "  Waiting for Fieshzen install to complete..."
for i in $(seq 1 36); do
  sleep 10
  if tail -5 "$LOG" | grep -q "successfully installed\|crashed\|ERROR"; then
    break
  fi
  echo "  ...still building ($((i*10))s)"
done

if tail -10 "$LOG" | grep -q "successfully installed"; then
  echo "  ✓ Fieshzen installed."
elif tail -10 "$LOG" | grep -q "crashed\|ERROR"; then
  echo "  ✗ Fieshzen install failed — check $LOG" >&2
  echo "  Continuing with Radarrzen anyway..."
fi
echo ""

# ── Deploy Radarrzen ─────────────────────────────────────────────────────────
echo "→ [2/3] Building + installing Radarrzen (Radarr browser)..."
R=$(curl -sf -X POST "$SAWSUBE_URL/api/tizenbrew/$TV_ID/build-install-radarrzen")
echo "  Job: $(echo "$R" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job_id','?'))" 2>/dev/null)"
echo ""

echo "  Waiting for Radarrzen install to complete..."
for i in $(seq 1 18); do
  sleep 10
  if tail -5 "$LOG" | grep -q "successfully installed\|crashed\|ERROR"; then
    break
  fi
  echo "  ...still building ($((i*10))s)"
done
echo ""

# ── Deploy Sonarrzen ─────────────────────────────────────────────────────────
echo "→ [3/3] Building + installing Sonarrzen (Sonarr browser)..."
R=$(curl -sf -X POST "$SAWSUBE_URL/api/tizenbrew/$TV_ID/build-install-sonarrzen")
echo "  Job: $(echo "$R" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job_id','?'))" 2>/dev/null)"
echo ""

echo "→ Streaming log (Ctrl+C to stop watching)..."
echo "  Look for: 'Tizen application is successfully installed'"
echo ""
tail -f "$LOG"
