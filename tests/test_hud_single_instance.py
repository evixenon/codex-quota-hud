"""Windows integration tests for the HUD's named single-instance guard."""

from __future__ import annotations

import os
import unittest

from hooks import session_start
from hud.codex_hud import HudInstanceGuard


@unittest.skipUnless(os.name == "nt", "Windows-only mutex API")
class HudInstanceGuardTests(unittest.TestCase):
    def test_only_one_guard_can_own_a_mutex_name(self) -> None:
        name = f"Local\\CodexQuotaHudTest-{os.getpid()}"
        first = HudInstanceGuard(name)
        second = HudInstanceGuard(name)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
        finally:
            first.close()
            second.close()

    def test_session_start_detects_the_hud_mutex(self) -> None:
        guard = HudInstanceGuard()
        try:
            self.assertTrue(guard.acquire())
            self.assertTrue(session_start._hud_is_running())
        finally:
            guard.close()


if __name__ == "__main__":
    unittest.main()
