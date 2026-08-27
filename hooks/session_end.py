"""Stop the HUD process belonging to the active Codex session."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def main() -> None:
    # Keep this aligned with session_start: PLUGIN_DATA changes per session.
    data_dir = Path.home() / ".codex-quota-hud"
    pid_file = data_dir / "hud.json"
    try:
        payload = json.loads(pid_file.read_text(encoding="utf-8"))
        pid = payload.get("pid")
    except (OSError, ValueError):
        pid = None

    if os.name == "nt" and isinstance(pid, int) and pid > 0:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    try:
        pid_file.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    main()
