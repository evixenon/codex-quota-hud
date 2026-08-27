"""Tests for compact reset-time HUD labels."""

from __future__ import annotations

from datetime import datetime
import unittest

from hud.codex_hud import format_reset_at


class ResetTimeFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuesday_morning = int(datetime(2026, 8, 25, 9, 7).timestamp())

    def test_short_window_shows_local_hour_and_minute(self) -> None:
        self.assertEqual(
            format_reset_at(self.tuesday_morning, weekly=False),
            "09:07",
        )

    def test_weekly_window_shows_english_weekday_and_hour(self) -> None:
        self.assertEqual(
            format_reset_at(self.tuesday_morning, weekly=True),
            "TUE09",
        )

    def test_missing_reset_time_uses_placeholder(self) -> None:
        self.assertEqual(format_reset_at(None, weekly=False), "--")


if __name__ == "__main__":
    unittest.main()
