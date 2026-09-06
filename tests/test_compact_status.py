"""Tests for the one-line quota HUD status."""

from __future__ import annotations

from datetime import datetime
import unittest

from hud.codex_hud import (
    QuotaWindow,
    UsageSnapshot,
    format_compact_status,
    select_next_reset_window,
)


class CompactStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = int(datetime(2026, 9, 7, 12, 0).timestamp())

    def snapshot(
        self,
        *,
        five_hour: QuotaWindow | None,
        weekly: QuotaWindow | None,
    ) -> UsageSnapshot:
        return UsageSnapshot(
            five_hour=five_hour,
            weekly=weekly,
            plan_type="pro",
            observed_at=float(self.now),
        )

    def test_selects_the_window_with_the_nearest_upcoming_reset(self) -> None:
        five_hour = QuotaWindow(
            remaining_percent=72,
            resets_at=self.now + 7200,
            window_minutes=300,
        )
        weekly = QuotaWindow(
            remaining_percent=64,
            resets_at=self.now + 3600,
            window_minutes=10080,
        )

        selected = select_next_reset_window(
            self.snapshot(five_hour=five_hour, weekly=weekly), now=self.now
        )

        self.assertEqual(selected, ("7D", True, weekly))

    def test_formats_only_quota_and_absolute_reset_time(self) -> None:
        reset_at = int(datetime(2026, 9, 7, 18, 45).timestamp())
        snapshot = self.snapshot(
            five_hour=QuotaWindow(72, reset_at, 300),
            weekly=QuotaWindow(64, self.now + 86400, 10080),
        )

        self.assertEqual(
            format_compact_status(snapshot, now=self.now),
            ("5H  72%  RESET 18:45", 72),
        )

    def test_missing_snapshot_uses_a_placeholder(self) -> None:
        self.assertEqual(
            format_compact_status(None, now=self.now),
            ("QUOTA --  RESET --", None),
        )


if __name__ == "__main__":
    unittest.main()
