#!/bin/sh
# Install (or reinstall) one of this repo's LaunchAgents from launchd/.
#   launchd/install.sh dispatcher            install / reload after editing the plist
#   launchd/install.sh git-sync
#   launchd/install.sh <name> uninstall      stop it and remove it from ~/Library/LaunchAgents
# Touches only com.cameronwood.nfl-<name>.
set -eu
NAME="${1:?usage: launchd/install.sh dispatcher|git-sync [uninstall]}"
LABEL="com.cameronwood.nfl-$NAME"
SRC="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
[ -f "$SRC" ] || { echo "No such plist: $SRC" >&2; exit 1; }

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "${2:-}" = "uninstall" ]; then
  rm -f "$DST"
  echo "Unloaded and removed $LABEL"
  exit 0
fi
plutil -lint "$SRC"
mkdir -p "$(dirname "$SRC")/../outputs/logs"
cp "$SRC" "$DST"
launchctl bootstrap "$DOMAIN" "$DST"
echo "Loaded $LABEL"
