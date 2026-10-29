#!/usr/bin/env bash
# Optional: add JobPortal to your Linux app menu, pointing at this checkout's run.sh. Undo with --remove.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS="$SHARE/applications"
ICONS="$SHARE/icons/hicolor/scalable/apps"
if [ "${1:-}" = "--remove" ]; then
  rm -f "$APPS/jobportal.desktop" "$ICONS/jobportal.svg"
  echo "Removed JobPortal from the app menu."
  exit 0
fi
mkdir -p "$APPS" "$ICONS"
cp "$ROOT/jobportal/static/icon.svg" "$ICONS/jobportal.svg"
sed "s|@EXEC@|\"$ROOT/run.sh\"|" "$ROOT/jobportal/resources/jobportal.desktop" > "$APPS/jobportal.desktop"
chmod +x "$APPS/jobportal.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$SHARE/icons/hicolor" 2>/dev/null || true
echo "JobPortal is in your app menu."
