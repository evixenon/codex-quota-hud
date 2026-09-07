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
    def test_existing_hud_mutex_prevents_another_launch(self) -> None:
        """The process-wide HUD guard must prevent another launch."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            with (
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

    def test_stale_pid_file_does_not_block_launch(self) -> None:
        """A dead HUD's PID record must not be used as a Windows process probe."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            shared_pid_file = home / ".codex-quota-hud" / "hud.json"
            shared_pid_file.parent.mkdir()
            shared_pid_file.write_text(
                json.dumps({"pid": 31415}), encoding="utf-8"
            )

            with (
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
                    "_hud_is_running",
                    return_value=False,
                ),
                patch.object(
                    session_start.os,
                    "kill",
                    side_effect=AssertionError("os.kill must not probe stale HUD PIDs"),
                ),
                patch.object(session_start.subprocess, "Popen") as popen,
            ):
                popen.return_value.pid = 27182
                session_start.main()

            popen.assert_called_once()

    def test_session_end_keeps_the_shared_hud_alive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            shared_pid_file = home / ".codex-quota-hud" / "hud.json"
            shared_pid_file.parent.mkdir()
            shared_pid_file.write_text(json.dumps({"pid": 31415}), encoding="utf-8")

            with patch.dict(
                os.environ,
                {"PLUGIN_DATA": str(home / "session-b")},
                clear=False,
            ):
                session_end.main()

            self.assertTrue(shared_pid_file.exists())
            self.assertEqual(
                json.loads(shared_pid_file.read_text(encoding="utf-8")),
                {"pid": 31415},
            )


if __name__ == "__main__":
    unittest.main()
