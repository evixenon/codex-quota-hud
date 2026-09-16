---
name: codex-quota-hud
description: Explain and troubleshoot the local Codex quota HUD plugin.
---

# Codex Quota HUD

This plugin starts or reuses the detached Windows HUD through Codex
`SessionStart`. Its `SessionEnd` hook intentionally leaves the shared HUD
running so session recycling does not make it disappear. Once started, the HUD
starts in compact mode near the top center of the screen, stays visible, and remains always on top when focus moves to other apps. The HUD displays the longest available
rate-limit window as the weekly-style quota and formats the reset countdown as
`5d20h`. Double-clicking the HUD or using its context menu toggles a compact
one-line mode, expanding downward and collapsing upward. Compact mode shows the quota and absolute reset time for the next window
to reset.

If the HUD does not appear, review and trust the plugin hook definition with
`/hooks`, confirm that Python with Tkinter is installed, and verify that
`codex --version` works in a normal terminal.
