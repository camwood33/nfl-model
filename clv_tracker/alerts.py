"""Best-effort macOS notification, so an unattended failure is seen without reading a log."""
from __future__ import annotations

import subprocess


def notify(message: str, title: str = "NFL git sync") -> None:
    message = message.replace('"', "'")
    try:
        subprocess.run(["/usr/bin/osascript", "-e",
                        f'display notification "{message}" with title "{title}" sound name "Basso"'],
                       timeout=10, capture_output=True)
    except Exception:
        pass
