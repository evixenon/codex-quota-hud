"""Regression tests for the cross-session HUD launcher guard."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hooks import session_end, session_start


class SessionStartTests(unittest.TestCase):
    def test_current_process_is_alive(self) -> None:
        """Windows must not use os.kill(pid, 0) as its process probe."""
        self.assertTrue(session_start._alive(os.getpid()))

    def test_existing_hud_mutex_prevents_another_launch(self) -> None:
        """A stale PID file must not bypass the process-wide HUD guard."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            with (
                patch.object(session_start.Path, "home", return_value=home),
                patch.dict(
                    os.environ,
                    {"PLUGIN_ROOT": str(home)},
                    clear=False,
                ),
                patch.object(
                    session_start,
                    "_hud_is_running",
                    return_value=True,
                    create=True,
                ),
                patch.object(session_start.subprocess, "Popen") as popen,
            ):
                popen.return_value.pid = 27182
                session_start.main()

            popen.assert_not_called()

    def test_second_session_reuses_living_hud_from_shared_data_dir(self) -> None:
        """A session-specific PLUGIN_DATA path must not bypass the process guard."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            existing_pid = 31415
            shared_pid_file = home / ".codex-quota-hud" / "hud.json"
            shared_pid_file.parent.mkdir()
            shared_pid_file.write_text(
                json.dumps({"pid": existing_pid}), encoding="utf-8"
            )

            with (
                patch.object(session_start.Path, "home", return_value=home),
                patch.dict(
                    os.environ,
                    {
                        "PLUGIN_DATA": str(home / "session-b"),
                        "PLUGIN_ROOT": str(home),
                    },
                    clear=False,
                ),
                patch.object(
                    session_start,
                    "_alive",
                    side_effect=lambda pid: pid == existing_pid,
                ),
                patch.object(session_start.subprocess, "Popen") as popen,
            ):
                popen.return_value.pid = 27182
                session_start.main()

            popen.assert_not_called()

    def test_session_end_uses_the_same_shared_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            shared_pid_file = home / ".codex-quota-hud" / "hud.json"
            shared_pid_file.parent.mkdir()
            shared_pid_file.write_text(json.dumps({"pid": 31415}), encoding="utf-8")

            with (
                patch.object(session_end.Path, "home", return_value=home),
                patch.dict(
                    os.environ,
                    {"PLUGIN_DATA": str(home / "session-b")},
                    clear=False,
                ),
                patch.object(session_end.subprocess, "run") as run,
            ):
                session_end.main()

            run.assert_called_once()
            self.assertFalse(shared_pid_file.exists())


if __name__ == "__main__":
    unittest.main()
