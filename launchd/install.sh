#!/bin/sh
# Install (or reinstall) the NFL dispatcher LaunchAgent from this repo.
#   launchd/install.sh            install / reload after editing the plist
#   launchd/install.sh uninstall  stop it and remove it from ~/Library/LaunchAgents
# Touches only com.cameronwood.nfl-dispatcher.
set -eu
LABEL=com.cameronwood.nfl-dispatcher
SRC="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "uninstall" ]; then
  rm -f "$DST"
  echo "Unloaded and removed $LABEL"
  exit 0
fi
plutil -lint "$SRC"
mkdir -p "$(dirname "$SRC")/../outputs/logs"
cp "$SRC" "$DST"
launchctl bootstrap "$DOMAIN" "$DST"
echo "Loaded $LABEL"
