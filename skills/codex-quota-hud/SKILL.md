---
name: codex-quota-hud
description: Explain and troubleshoot the local Codex quota HUD plugin.
---

# Codex Quota HUD

This plugin starts or reuses the detached Windows HUD through Codex
`SessionStart`. Its `SessionEnd` hook intentionally leaves the shared HUD
running so session recycling does not make it disappear. While it is running, the HUD watches the Windows
foreground window: it appears for Codex (or its ChatGPT desktop host) and hides
when focus moves to another app. The HUD displays the longest available
rate-limit window as the weekly-style quota and formats the reset countdown as
`5d20h`.

If the HUD does not appear, review and trust the plugin hook definition with
`/hooks`, confirm that Python with Tkinter is installed, and verify that
`codex --version` works in a normal terminal.
